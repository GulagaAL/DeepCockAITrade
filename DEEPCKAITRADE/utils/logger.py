# utils/logger.py
import logging
from logging.handlers import RotatingFileHandler
import os
import sys

def setup_logger():
    logger = logging.getLogger("deepckaitrade")
    if logger.hasHandlers():
        logger.handlers.clear()

    logger.setLevel(logging.INFO)

    # Формат без эмодзи в консоли Windows
    console_formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')
    file_formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')

    # Консольный хендлер — без эмодзи на Windows
    ch = logging.StreamHandler(sys.stdout)
    if os.name == 'nt':  # Windows
        # Убираем эмодзи только из вывода в консоль
        def clean_message(record):
            record.msg = record.msg.replace("BACKTEST", "BACKTEST") \
                                   .replace("LIVE", "LIVE") \
                                   .replace("Загрузка", "Zagruzka") \
                                   .replace("Тест", "Test")
            # Можно просто оставить как есть — главное не падать
            return True
        ch.addFilter(clean_message)
    ch.setFormatter(console_formatter)
    logger.addHandler(ch)

    # Файловый хендлер — с эмодзи (UTF-8)
    os.makedirs("logs", exist_ok=True)
    fh = RotatingFileHandler("logs/app.log", maxBytes=10*1024*1024, backupCount=5, encoding="utf-8")
    fh.setFormatter(file_formatter)
    logger.addHandler(fh)

    return logger

logger = setup_logger()