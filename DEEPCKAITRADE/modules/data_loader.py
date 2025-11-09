import os
import json
import time
import schedule
from datetime import datetime, timedelta
import pandas as pd
import pytz
from tinkoff.invest import Client, CandleInterval, RequestError

# ✅ ВСЕ ИМПОРТЫ В НАЧАЛЕ ФАЙЛА
from config import Config
from modules.indicators import calculate_indicators
from modules.portfolio_tracker import get_current_positions
from modules.api_client import DeepSeekClient
from backtest.prediction_handler import PredictionHandler 

def fetch_market_data():
    """Получает данные с биржи и формирует JSON для промпта"""
    config = Config()
    os.makedirs(config.DATA_DIR, exist_ok=True)
    
    try:
        with Client(config.TINKOFF_TOKEN) as client:
            # 1. Текущая свеча и история
            to_time = datetime.utcnow().replace(tzinfo=pytz.utc)
            from_time = to_time - timedelta(days=config.HISTORY_DAYS)
            
            candles = client.get_all_candles(
                figi=config.INSTRUMENT_FIGI,
                from_=from_time,
                to=to_time,
                interval=CandleInterval.CANDLE_INTERVAL_5_MIN
            )
            
            # 2. Конвертация в DataFrame
            df = pd.DataFrame([{
                'time': c.time,
                'open': cast_money(c.open),
                'high': cast_money(c.high),
                'low': cast_money(c.low),
                'close': cast_money(c.close),
                'volume': c.volume
            } for c in candles])
            
            if df.empty:
                raise ValueError("No candle data received")
            
            # 3. Расчёт индикаторов
            indicators = calculate_indicators(df)
            
            # 4. Текущие позиции
            positions = get_current_positions(client, config.ACCOUNT_ID, config.INSTRUMENT_FIGI)
            
            # 5. Спецификации инструмента
            instrument = client.instruments.get_by_figi(figi=config.INSTRUMENT_FIGI).instrument
            
            # 6. Формирование финального JSON
            data = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "market_data": {
                    "price_current": df['close'].iloc[-1],
                    "candle_current": {
                        "open": df['open'].iloc[-1],
                        "high": df['high'].iloc[-1],
                        "low": df['low'].iloc[-1],
                        "close": df['close'].iloc[-1]
                    },
                    "volume_current": int(df['volume'].iloc[-1]),
                    "indicators": indicators,
                    "patterns": detect_patterns(df, indicators)
                },
                "risk_params": {
                    "account_equity": get_account_equity(client, config.ACCOUNT_ID),
                    "max_risk_per_trade_pct": config.RISK_PER_TRADE_PCT,
                    "max_exposure_per_asset_pct": config.MAX_EXPOSURE_PCT,
                    "min_risk_reward": config.MIN_RISK_REWARD,
                    "volatility_threshold": config.VOLATILITY_THRESHOLD
                },
                "instrument_specs": {
                    "symbol": instrument.ticker,
                    "asset_class": map_asset_type(instrument),
                    "tick_value": float(instrument.min_price_increment),
                    "min_order_size": int(instrument.lot),
                    "avg_daily_volume": estimate_avg_volume(df),
                    "margin_requirement": 0
                },
                "current_positions": positions,
                "cost_structure": {
                    "commission_per_share": config.COMMISSION_PER_SHARE,
                    "fixed_commission": config.FIXED_COMMISSION,
                    "max_slippage": config.MAX_SLIPPAGE
                }
            }
            
            # 7. Сохранение
            timestamp = datetime.now(config.TIMEZONE).strftime("%Y%m%d_%H%M%S")
            filename = f"{config.DATA_DIR}/market_data_{timestamp}.json"
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            print(f"[{datetime.now(config.TIMEZONE)}] Data saved to {filename}")
            return filename
            
    except RequestError as e:
        print(f"API Error: {e.details}")
        return None
    except Exception as e:
        print(f"Critical error: {str(e)}")
        return None

def fetch_and_predict():
    """Основной workflow: загрузка данных → прогноз → сохранение"""
    start_time = time.time()
    config = Config()
    deepseek_client = DeepSeekClient()
    
    # ✅ Больше не нужно импортировать здесь
    prediction_handler = PredictionHandler()
    
    try:
        # 1. Загружаем рыночные данные
        market_data_file = fetch_market_data()
        if not market_data_file:
            print("[ERROR] Не удалось загрузить рыночные данные. Пропускаем прогноз.")
            return
        
        # 2. Читаем сохранённые данные
        with open(market_data_file, 'r', encoding='utf-8') as f:
            market_data = json.load(f)
        
        # 3. Получаем прогноз от DeepSeek
        api_start = time.time()
        prediction = deepseek_client.get_prediction(market_data)
        api_latency = time.time() - api_start
        
        # 4. Сохраняем прогноз
        prediction_handler.save_prediction(market_data, prediction, api_latency)
        
        total_time = time.time() - start_time
        print(f"[WORKFLOW] Полный цикл: {total_time:.2f} сек | API: {api_latency:.2f} сек")
        
        # 5. Опционально: отправляем уведомление о сделке
        if prediction["action"] in ["BUY", "SELL"] and prediction["confidence"] >= 80:
            send_trade_alert(prediction, market_data)
            
    except Exception as e:
        print(f"[CRITICAL] Ошибка в основном workflow: {str(e)}")

def send_trade_alert(prediction, market_data):
    """Отправляет уведомление о высококонфиденциальной сделке"""
    symbol = market_data["instrument_specs"]["symbol"]
    message = (
        f"🚨 ВЫСОКАЯ УВЕРЕННОСТЬ ({prediction['confidence']}%)\n"
        f"📈 СИГНАЛ: {prediction['action']} {prediction['size']} {symbol}\n"
        f"💰 Цена входа: ${prediction['entry_price']:.2f}\n"
        f"🛑 SL: ${prediction['stop_loss']:.2f} | 🎯 TP: ${prediction['take_profit']:.2f}\n"
        f"⚖️ Риск: {prediction['risk_percent']:.2f}% от портфеля"
    )
    print(f"[ALERT] {message}")

def run_scheduler():
    schedule.every(20).seconds.do(fetch_and_predict)
    print("Система запущена. Цикл: 20 секунд.")
    print(f"Торгуемый инструмент: {Config().INSTRUMENT_FIGI}")
    
    while True:
        schedule.run_pending()
        time.sleep(0.5)

# ✅ ДОБАВЛЕНЫ НЕДОСТАЮЩИЕ ФУНКЦИИ:

def cast_money(money):
    return money.units + money.nano / 1e9

def get_account_equity(client, account_id):
    """Получает текущую equity с брокера"""
    try:
        portfolio = client.operations.get_portfolio(account_id=account_id)
        total_value = 0.0
        for position in portfolio.positions:
            current_price = client.market_data.get_last_prices(figi=[position.figi]).last_prices[0].price
            total_value += cast_money(current_price) * position.quantity.units
        return total_value
    except Exception as e:
        print(f"[ERROR] Не удалось получить equity: {str(e)}")
        return 10000.0

def map_asset_type(instrument):
    """Конвертирует тип инструмента в формат, понятный промпту"""
    mapping = {
        "STOCK": "equity",
        "CURRENCY": "forex",
        "FUTURES": "futures",
        "BOND": "bond",
        "ETF": "etf"
    }
    return mapping.get(instrument.type.upper(), "unknown")

def estimate_avg_volume(df):
    """Оценивает средний объём на основе истории"""
    if len(df) < 100:
        return 1000000
    return int(df['volume'].rolling(100).mean().iloc[-1])

def detect_patterns(df, indicators):
    """Обнаружение паттернов (упрощённо)"""
    patterns = {"candlestick": [], "support_resistance": [], "price_action": []}
    
    # Bullish engulfing
    if (len(df) >= 2 and 
        df['close'].iloc[-1] > df['open'].iloc[-1] and 
        df['open'].iloc[-2] > df['close'].iloc[-2] and
        df['open'].iloc[-1] < df['close'].iloc[-2] and 
        df['close'].iloc[-1] > df['open'].iloc[-2]):
        patterns["candlestick"].append("bullish_engulfing")
    
    # Тестирование сопротивления
    if abs(indicators["bollinger"]["upper"] - df['high'].iloc[-1]) < 0.1:
        patterns["support_resistance"].append(f"resistance_{indicators['bollinger']['upper']:.2f}_tested")
    
    return patterns

if __name__ == "__main__":
    run_scheduler()