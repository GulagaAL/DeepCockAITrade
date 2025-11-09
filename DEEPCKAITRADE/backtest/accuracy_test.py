import os
import json
import time
from datetime import datetime, timedelta
import pandas as pd
import pytz
from tinkoff.invest import Client, CandleInterval
from modules.api_client import DeepSeekClient
from modules.indicators import calculate_indicators
from modules.data_loader import cast_money, detect_patterns
from config import Config
from backtest.prediction_validator import PredictionValidator

def run_accuracy_test():
    """Запускает тест точности DeepSeek на исторических данных"""
    config = Config()
    validator = PredictionValidator(lookahead_candles=6)  # 30 минут = 6 * M5
    deepseek_client = DeepSeekClient()
    
    print(f"🔍 Тест точности DeepSeek с {config.BACKTEST_START} по {config.BACKTEST_END}")
    print(f"📊 Используем {validator.lookahead_candles} свечей (M5) для проверки прогноза")
    
    # 1. Загрузка исторических данных
    start_date = datetime.strptime(config.BACKTEST_START, "%Y-%m-%d").replace(tzinfo=pytz.utc)
    end_date = datetime.strptime(config.BACKTEST_END, "%Y-%m-%d").replace(tzinfo=pytz.utc)
    
    with Client(config.TINKOFF_TOKEN) as client:
        print("📥 Загрузка M5-данных...")
        candles = client.get_all_candles(
            figi=config.INSTRUMENT_FIGI,
            from_=start_date,
            to=end_date,
            interval=CandleInterval.CANDLE_INTERVAL_5_MIN
        )
        
        df = pd.DataFrame([{
            'time': c.time,
            'open': cast_money(c.open),
            'high': cast_money(c.high),
            'low': cast_money(c.low),
            'close': cast_money(c.close),
            'volume': c.volume
        } for c in candles])
        
        if df.empty:
            raise ValueError("Нет исторических данных!")
        
        print(f"✅ Загружено {len(df)} M5-свечей")
    
    # 2. Расчёт индикаторов для всех свечей (一次性计算)
    print("📈 Расчёт индикаторов...")
    # Создаём копию с ATR для валидации
    df_with_indicators = df.copy()
    # Добавляем ATR в df (для валидации)
    from ta.volatility import AverageTrueRange
    df_with_indicators['atr'] = AverageTrueRange(
        high=df_with_indicators['high'], 
        low=df_with_indicators['low'], 
        close=df_with_indicators['close'], 
        window=14
    ).average_true_range()
    
    print("🤖 Тестирование точности прогнозов...")
    
    results = []
    successful_predictions = 0
    
    for idx in range(50, len(df) - validator.lookahead_candles):  # Пропускаем первые 50 для индикаторов
        current_row = df.iloc[:idx+1].copy()
        current_price = current_row['close'].iloc[-1]
        timestamp = current_row['time'].iloc[-1]
        
        # Формирование market_data (аналогично live-режиму)
        try:
            indicators = calculate_indicators(current_row)
            patterns = detect_patterns(current_row, indicators)
        except Exception as e:
            print(f"[SKIP] Ошибка индикаторов на {timestamp}: {str(e)}")
            continue
        
        market_data = {
            "timestamp": timestamp.isoformat() + "Z",
            "market_data": {
                "price_current": current_price,
                "candle_current": {
                    "open": current_row['open'].iloc[-1],
                    "high": current_row['high'].iloc[-1],
                    "low": current_row['low'].iloc[-1],
                    "close": current_price
                },
                "volume_current": int(current_row['volume'].iloc[-1]),
                "indicators": indicators,
                "patterns": patterns
            },
            "risk_params": {
                "account_equity": 10000.00,  # Фиктивное значение для API
                "max_risk_per_trade_pct": config.RISK_PER_TRADE_PCT,
                "max_exposure_per_asset_pct": config.MAX_EXPOSURE_PCT,
                "min_risk_reward": config.MIN_RISK_REWARD,
                "volatility_threshold": config.VOLATILITY_THRESHOLD
            },
            "instrument_specs": {
                "symbol": "TEST",
                "asset_class": "equity",
                "tick_value": 0.01,
                "min_order_size": 1,
                "avg_daily_volume": 1000000,
                "margin_requirement": 0
            },
            "current_positions": {},
            "cost_structure": {
                "commission_per_share": config.COMMISSION_PER_SHARE,
                "fixed_commission": config.FIXED_COMMISSION,
                "max_slippage": config.MAX_SLIPPAGE
            }
        }
        
        # 3. Отправка в DeepSeek и получение прогноза
        try:
            prediction = deepseek_client.get_prediction(market_data)
            successful_predictions += 1
            
            # 4. Проверка точности прогноза
            validation_result = validator.validate_prediction(prediction, idx, df_with_indicators)
            
            # Сохраняем результат
            result_entry = {
                "timestamp": timestamp.isoformat(),
                "prediction": prediction,
                "validation": validation_result,
                "current_price": current_price,
                "future_slice": df_with_indicators.iloc[idx + 1 : idx + 1 + validator.lookahead_candles][['time', 'high', 'low', 'close']].to_dict('records')
            }
            results.append(result_entry)
            
            # Логируем прогнозы с высокой уверенностью
            if prediction["confidence"] >= 80:
                status = "✅" if validation_result["accuracy"] == "correct" else "❌" if validation_result["accuracy"] == "incorrect" else "⚠️"
                print(f"[{timestamp.strftime('%m-%d %H:%M')}] {status} {prediction['action']} @ ${current_price:.2f} (conf: {prediction['confidence']}%) -> {validation_result['accuracy']} ({validation_result['reason']})")
            
            # Задержка для API (избегаем рейт-лимитов)
            time.sleep(0.5)
            
        except Exception as e:
            print(f"[API ERROR] {timestamp}: {str(e)}")
            continue
    
    # 5. Сбор метрик и сохранение
    metrics = validator.calculate_accuracy_metrics(results)
    
    # Сохранение результатов
    os.makedirs("accuracy_results", exist_ok=True)
    filename = f"accuracy_results/accuracy_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    final_report = {
        "metadata": {
            "start_date": config.BACKTEST_START,
            "end_date": config.BACKTEST_END,
            "instrument": config.INSTRUMENT_FIGI,
            "total_candles_processed": len(df),
            "successful_predictions": successful_predictions,
            "lookahead_minutes": validator.lookahead_candles * 5
        },
        "metrics": metrics
    }
    
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(final_report, f, indent=2, ensure_ascii=False)
    
    print("\n" + "="*60)
    print("📊 РЕЗУЛЬТАТЫ ТЕСТА ТОЧНОСТИ DEEPSEEK")
    print("="*60)
    print(f"📈 Обработано прогнозов: {metrics['total_predictions']}")
    print(f"✅ Точные прогнозы: {metrics['correct_predictions']}")
    print(f"❌ Неточные прогнозы: {metrics['incorrect_predictions']}")
    print(f"⚠️  Частичные: {metrics['partial_predictions']}")
    print(f"🎯 Общая точность: {metrics['accuracy_rate']}%")
    print(f"🎯 Точность BUY: {metrics['precision_buy']}%")
    print(f"🎯 Точность SELL: {metrics['precision_sell']}%")
    print(f"💾 Отчёт сохранён: {filename}")
    print("="*60)
    
    return final_report

if __name__ == "__main__":
    run_accuracy_test()