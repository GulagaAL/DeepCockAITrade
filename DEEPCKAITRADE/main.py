# DEEPCKAITRADE/main.py
from config import Config

def run_live_mode():
    """Запуск live-режима с таймером"""
    from modules.data_loader import run_scheduler
    print("🚀 LIVE-РЕЖИМ: Загрузка данных каждые 20 секунд...")
    run_scheduler()

def run_backtest_mode():
    """Запуск тестирования точности на исторических данных"""
    from backtest.accuracy_test import run_accuracy_test
    print("📊 BACKTEST РЕЖИМ: Тестирование точности DeepSeek...")
    run_accuracy_test()

if __name__ == "__main__":
    config = Config()
    
    if config.MODE == "LIVE":
        run_live_mode()
    elif config.MODE == "BACKTEST":
        run_backtest_mode()
    else:
        print(f"❌ Неизвестный режим: {config.MODE}")
        print("Допустимые значения: LIVE, BACKTEST")