import os
import json
import time
from datetime import datetime, timedelta
import pandas as pd
import pytz
from tinkoff.invest import Client, CandleInterval
from tinkoff.invest.exceptions import RequestError

from DEEPCKAITRADE.modules.api_client import DeepSeekClient
from DEEPCKAITRADE.modules.indicators import calculate_indicators
from DEEPCKAITRADE.modules.data_loader import cast_money, detect_patterns
from DEEPCKAITRADE.config import Config
from DEEPCKAITRADE.backtest.prediction_validator import PredictionValidator
from DEEPCKAITRADE.utils.logger import logger


def run_accuracy_test():
    config = Config()
    validator = PredictionValidator(lookahead_candles=6)  # 30 мин
    deepseek_client = DeepSeekClient()  # Синглтон

    logger.info(f"Тест точности с {config.BACKTEST_START} по {config.BACKTEST_END}")

    start_date = datetime.strptime(config.BACKTEST_START, "%Y-%m-%d").replace(tzinfo=pytz.utc)
    end_date = datetime.strptime(config.BACKTEST_END, "%Y-%m-%d").replace(tzinfo=pytz.utc)

    with Client(config.TINKOFF_TOKEN) as client:
        logger.info("Загрузка исторических данных...")
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

        logger.info(f"Загружено {len(df)} свечей")

    # Добавляем ATR для валидации
    from ta.volatility import AverageTrueRange
    df['atr'] = AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=14).average_true_range()

    results = []
    successful_predictions = 0

    for idx in range(50, len(df) - validator.lookahead_candles):
        current_df = df.iloc[:idx + 1].copy()
        current_price = current_df['close'].iloc[-1]
        timestamp = current_df['time'].iloc[-1]

        try:
            indicators = calculate_indicators(current_df)
            patterns = detect_patterns(current_df, indicators)
        except Exception as e:
            logger.warning(f"[Test] Skip {timestamp}: {e}")
            continue

        market_data = {
            "timestamp": timestamp.isoformat() + "Z",
            "market_data": {
                "price_current": float(current_price),
                "candle_current": {
                    "open": float(current_df['open'].iloc[-1]),
                    "high": float(current_df['high'].iloc[-1]),
                    "low": float(current_df['low'].iloc[-1]),
                    "close": float(current_price)
                },
                "volume_current": int(current_df['volume'].iloc[-1]),
                "indicators": indicators,
                "patterns": patterns
            },
            "risk_params": {
                "account_equity": 10000.0,  # Фикс для теста
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

        try:
            prediction = deepseek_client.get_prediction(market_data)
            successful_predictions += 1

            validation_result = validator.validate_prediction(prediction, idx, df)

            result_entry = {
                "timestamp": timestamp.isoformat(),
                "prediction": prediction,
                "validation": validation_result,
                "current_price": float(current_price),
                "future_slice": df.iloc[idx + 1: idx + 1 + validator.lookahead_candles][
                    ['time', 'high', 'low', 'close']].to_dict('records')
            }
            results.append(result_entry)

            if prediction["confidence"] >= 80:
                status = "✅" if validation_result["accuracy"] == "correct" else "❌" if validation_result[
                                                                                           "accuracy"] == "incorrect" else "⚠️"
                logger.info(
                    f"[{timestamp.strftime('%m-%d %H:%M')}] {status} {prediction['action']} @ {current_price:.2f} (conf: {prediction['confidence']}%)")

            time.sleep(0.5)  # Rate limit

        except Exception as e:
            logger.error(f"[Test API] {timestamp}: {e}")
            continue

    metrics = validator.calculate_accuracy_metrics(results)

    os.makedirs(config.ACCURACY_RESULTS_DIR, exist_ok=True)
    filename = f"{config.ACCURACY_RESULTS_DIR}/accuracy_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    final_report = {
        "metadata": {
            "start_date": config.BACKTEST_START,
            "end_date": config.BACKTEST_END,
            "instrument": config.INSTRUMENT_FIGI,
            "total_candles": len(df),
            "successful_predictions": successful_predictions,
            "lookahead_minutes": validator.lookahead_candles * 5
        },
        "metrics": metrics
    }

    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(final_report, f, indent=2, ensure_ascii=False)

    logger.info("=" * 60)
    logger.info("РЕЗУЛЬТАТЫ ТЕСТА ТОЧНОСТИ")
    logger.info(f"Обработано: {metrics['total_predictions']}")
    logger.info(f"Точные: {metrics['correct_predictions']}")
    logger.info(f"Неточные: {metrics['incorrect_predictions']}")
    logger.info(f"Общая точность: {metrics['accuracy_rate']:.1f}%")
    logger.info(f"Сохранено: {filename}")
    logger.info("=" * 60)

    return final_report


if __name__ == "__main__":
    run_accuracy_test()