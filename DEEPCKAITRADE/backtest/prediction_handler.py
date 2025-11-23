import os
import json
from datetime import datetime
from DEEPCKAITRADE.utils.logger import setup_logger, logger
from DEEPCKAITRADE.config import Config

class PredictionHandler:
    def __init__(self):
        self.config = Config()
        # Используем директорию из config, а не отдельную
        self.prediction_dir = self.config.PREDICTIONS_DIR
        os.makedirs(self.prediction_dir, exist_ok=True)
    
    def save_prediction(self, market_data, prediction, latency=0.0):
        """Сохраняет прогноз с метаданными в файл"""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"pred_{timestamp}.json"
        filepath = os.path.join(self.prediction_dir, filename)
        
        # Формируем полную запись с контекстом
        record = {
            "metadata": {
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "latency_sec": latency,
                "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                "instrument": market_data["instrument_specs"]["symbol"]
            },
            "input_data": market_data,
            "prediction": prediction
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(record, f, indent=2, ensure_ascii=False)
        
        print(f"[PREDICTION] Сохранено: {filename} | Действие: {prediction['action']} | Уверенность: {prediction['confidence']}")
        return filepath
    
    def get_latest_prediction(self):
        """Возвращает последний прогноз из папки"""
        prediction_files = sorted(
            [f for f in os.listdir(self.prediction_dir) if f.startswith("pred_")],
            reverse=True
        )
        
        if not prediction_files:
            return None
        
        latest_file = os.path.join(self.prediction_dir, prediction_files[0])
        with open(latest_file, 'r', encoding='utf-8') as f:
            return json.load(f)["prediction"]