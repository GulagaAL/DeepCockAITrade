import os
import json
import time
import schedule
from datetime import datetime, timedelta
import pandas as pd
import pytz
from tinkoff.invest import Client, CandleInterval
from tinkoff.invest.exceptions import RequestError

from DEEPCKAITRADE.config import Config
from DEEPCKAITRADE.modules.indicators import calculate_indicators
from DEEPCKAITRADE.modules.portfolio_tracker import get_current_positions
from DEEPCKAITRADE.modules.api_client import DeepSeekClient
from DEEPCKAITRADE.backtest.prediction_handler import PredictionHandler
from DEEPCKAITRADE.utils.logger import logger

# Глобальный кэш для свечей (один на процесс)
_candles_cache = None
_last_update = None


def cast_money(money):
    return money.units + money.nano / 1e9


def fetch_market_data():
    """Получает данные с биржи и формирует JSON для промпта. С кэшированием."""
    global _candles_cache, _last_update
    config = Config()
    os.makedirs(config.DATA_DIR, exist_ok=True)

    try:
        with Client(config.TINKOFF_TOKEN) as client:
            now = datetime.utcnow().replace(tzinfo=pytz.utc)

            # Кэширование: полный запрос раз в 60 сек, иначе - только новые свечи
            if _candles_cache is None or (now - _last_update).total_seconds() > 60:
                from_time = now - timedelta(days=config.HISTORY_DAYS)
                candles = client.get_all_candles(
                    figi=config.INSTRUMENT_FIGI,
                    from_=from_time,
                    to=now,
                    interval=CandleInterval.CANDLE_INTERVAL_5_MIN
                )
                _candles_cache = pd.DataFrame([{
                    'time': c.time,
                    'open': cast_money(c.open),
                    'high': cast_money(c.high),
                    'low': cast_money(c.low),
                    'close': cast_money(c.close),
                    'volume': c.volume
                } for c in candles])
                _last_update = now
                logger.info(f"[Data] Полный кэш обновлён: {len(_candles_cache)} свечей")
            else:
                # Только новые
                last_time = _candles_cache['time'].max()
                new_candles = client.get_all_candles(
                    figi=config.INSTRUMENT_FIGI,
                    from_=last_time,
                    to=now,
                    interval=CandleInterval.CANDLE_INTERVAL_5_MIN
                )
                if new_candles:
                    new_df = pd.DataFrame([{
                        'time': c.time,
                        'open': cast_money(c.open),
                        'high': cast_money(c.high),
                        'low': cast_money(c.low),
                        'close': cast_money(c.close),
                        'volume': c.volume
                    } for c in new_candles])
                    _candles_cache = pd.concat([_candles_cache, new_df]).drop_duplicates('time').sort_values('time')
                    logger.info(f"[Data] Добавлено {len(new_df)} новых свечей")

            df = _candles_cache.copy()
            if df.empty:
                raise ValueError("No candle data received")

            # Расчёт индикаторов
            indicators = calculate_indicators(df)

            # Текущие позиции
            positions = get_current_positions(client, config.ACCOUNT_ID, config.INSTRUMENT_FIGI)

            # Спецификации инструмента
            instrument = client.instruments.get_by_figi(figi=config.INSTRUMENT_FIGI).instrument

            # Текущий equity
            current_equity = get_account_equity(client, config.ACCOUNT_ID)

            # Формирование JSON
            data = {
                "timestamp": now.isoformat() + "Z",
                "market_data": {
                    "price_current": float(df['close'].iloc[-1]),
                    "candle_current": {
                        "open": float(df['open'].iloc[-1]),
                        "high": float(df['high'].iloc[-1]),
                        "low": float(df['low'].iloc[-1]),
                        "close": float(df['close'].iloc[-1])
                    },
                    "volume_current": int(df['volume'].iloc[-1]),
                    "indicators": indicators,
                    "patterns": detect_patterns(df, indicators)
                },
                "risk_params": {
                    "account_equity": float(current_equity),
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
                "current_positions": positions,  # Теперь словарь с ключом
                "cost_structure": {
                    "commission_per_share": config.COMMISSION_PER_SHARE,
                    "fixed_commission": config.FIXED_COMMISSION,
                    "max_slippage": config.MAX_SLIPPAGE
                }
            }

            # Сохранение
            timestamp = datetime.now(config.TIMEZONE).strftime("%Y%m%d_%H%M%S")
            filename = f"{config.DATA_DIR}/market_data_{timestamp}.json"
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            logger.info(f"[Data] Сохранено: {filename}")
            return data  # Возвращаем dict, не файл

    except RequestError as e:
        logger.error(f"[Tinkoff API] {e.details}")
        return None
    except Exception as e:
        logger.error(f"[Data] Critical error: {str(e)}")
        return None


def fetch_and_predict():
    """Основной workflow"""
    start_time = time.time()
    deepseek_client = DeepSeekClient()  # Синглтон - один на все вызовы
    prediction_handler = PredictionHandler()

    market_data = fetch_market_data()
    if not market_data:
        logger.error("[Workflow] Не удалось загрузить данные. Пропуск.")
        return

    try:
        api_start = time.time()
        prediction = deepseek_client.get_prediction(market_data)
        api_latency = time.time() - api_start

        prediction_handler.save_prediction(market_data, prediction, api_latency)

        total_time = time.time() - start_time
        logger.info(
            f"[Workflow] Цикл: {total_time:.2f}s | API: {api_latency:.2f}s | Action: {prediction['action']} ({prediction['confidence']}%)")

        if prediction["action"] in ["BUY", "SELL"] and prediction["confidence"] >= 80:
            send_trade_alert(prediction, market_data)

    except Exception as e:
        logger.error(f"[Workflow] Error: {str(e)}")


def send_trade_alert(prediction, market_data):
    symbol = market_data["instrument_specs"]["symbol"]
    message = (
        f"HIGH CONFIDENCE ({prediction['confidence']}%)\\n"
        f"SIGNAL: {prediction['action']} {prediction['size']} {symbol}\\n"
        f"Entry: ${prediction['entry_price']:.2f}\\n"
        f"SL: ${prediction['stop_loss']:.2f} | TP: ${prediction['take_profit']:.2f}\\n"
        f"Risk: {prediction['risk_percent']:.2f}%"
    )
    logger.info(f"[Alert] {message}")


def run_scheduler():
    schedule.every(20).seconds.do(fetch_and_predict)
    logger.info("Система запущена. Цикл: 20 секунд.")
    logger.info(f"Инструмент: {Config().INSTRUMENT_FIGI}")

    while True:
        schedule.run_pending()
        time.sleep(0.5)


# Вспомогательные функции (без изменений, но с логами)
def get_account_equity(client, account_id):
    try:
        portfolio = client.operations.get_portfolio(account_id=account_id)
        total_value = portfolio.total_amount_shares.units + portfolio.total_amount_shares.nano / 1e9
        return total_value
    except Exception as e:
        logger.error(f"[Equity] Error: {str(e)}")
        return Config().INITIAL_BALANCE  # Fallback


def map_asset_type(instrument):
    mapping = {
        "STOCK": "equity",
        "CURRENCY": "forex",
        "FUTURES": "futures",
        "BOND": "bond",
        "ETF": "etf"
    }
    return mapping.get(instrument.type.name, "unknown") if instrument.type else "unknown"


def estimate_avg_volume(df):
    if len(df) < 100:
        return 1000000
    return int(df['volume'].rolling(100).mean().iloc[-1])


def detect_patterns(df, indicators):
    patterns = {"candlestick": [], "support_resistance": [], "price_action": []}

    # Bullish engulfing (пример)
    if len(df) >= 2 and (
            df['close'].iloc[-1] > df['open'].iloc[-1] and
            df['open'].iloc[-2] > df['close'].iloc[-2] and
            df['open'].iloc[-1] < df['close'].iloc[-2] and
            df['close'].iloc[-1] > df['open'].iloc[-2]
    ):
        patterns["candlestick"].append("bullish_engulfing")

    # Resistance test
    if abs(indicators["bollinger"]["upper"] - df['high'].iloc[-1]) < 0.1:
        patterns["support_resistance"].append(f"resistance_{indicators['bollinger']['upper']:.2f}_tested")

    return patterns


if __name__ == "__main__":
    run_scheduler()