from DEEPCKAITRADE.modules.data_loader import fetch_and_predict
from DEEPCKAITRADE.utils.logger import logger
import time

def run_strategy():
    logger.info("Strategy Engine запущен в live-режиме")
    # Здесь логика стратегии, вызов fetch_and_predict()
    while True:
        fetch_and_predict()
        time.sleep(20)