from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import pytz

load_dotenv()

class Config:
    # API и идентификаторы
    TINKOFF_TOKEN = os.getenv("TINKOFF_TOKEN")
    ACCOUNT_ID = os.getenv("ACCOUNT_ID")
    INSTRUMENT_FIGI = os.getenv("INSTRUMENT_FIGI")

    # Режим работы
    MODE = os.getenv("MODE", "BACKTEST")

    # Пути к данным
    DATA_DIR = "data"
    RAW_DATA_DIR = os.path.join(DATA_DIR, "raw")
    PREDICTIONS_DIR = os.path.join(DATA_DIR, "predictions")
    ACCURACY_RESULTS_DIR = os.path.join(DATA_DIR, "accuracy_results")

    # Параметры бэктеста
    backtest_start_str = os.getenv("BACKTEST_START")
    if backtest_start_str:
        BACKTEST_START = backtest_start_str
    else:
        BACKTEST_START = (datetime.utcnow() - timedelta(weeks=3)).strftime("%Y-%m-%d")

    backtest_end_str = os.getenv("BACKTEST_END")
    if backtest_end_str:
        BACKTEST_END = backtest_end_str
    else:
        BACKTEST_END = datetime.utcnow().strftime("%Y-%m-%d")
    INITIAL_BALANCE = float(os.getenv("INITIAL_BALANCE", "100000.00"))
    SIMULATION_STEP = "5min"

    # Риск-параметры
    RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", "1.0"))
    MAX_EXPOSURE_PCT = float(os.getenv("MAX_EXPOSURE_PCT", "5.0"))
    MIN_RISK_REWARD = float(os.getenv("MIN_RISK_REWARD", "1.5"))
    VOLATILITY_THRESHOLD = float(os.getenv("VOLATILITY_THRESHOLD", "2.0"))

    # Технические параметры
    TIMEZONE = pytz.timezone("Europe/Moscow")
    CANDLE_INTERVAL = "5min"
    HISTORY_DAYS = 2

    # Комиссии и издержки
    COMMISSION_PER_SHARE = 0.004
    FIXED_COMMISSION = 1.00
    MAX_SLIPPAGE = 0.02

    # Параметры DeepSeek API
    DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
    DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    DEEPSEEK_TIMEOUT = int(os.getenv("DEEPSEEK_TIMEOUT", "30"))

    # Резервные параметры
    FALLBACK_CONFIDENCE = 50
    MAX_API_RETRIES = 3
    COOLDOWN_AFTER_FAILURE = 60

    @classmethod
    def validate(cls):
        """Выполняет валидацию всех обязательных параметров"""
        if not cls.TINKOFF_TOKEN or not cls.ACCOUNT_ID or not cls.INSTRUMENT_FIGI:
            raise ValueError("Missing required .env variables: TINKOFF_TOKEN, ACCOUNT_ID, INSTRUMENT_FIGI")

        if not cls.DEEPSEEK_API_KEY:
            raise ValueError("DEEPSEEK_API_KEY не указан в .env")


# Автовалидация при импорте
Config.validate()