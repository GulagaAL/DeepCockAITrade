import pandas as pd
from datetime import timedelta
import numpy as np

class PredictionValidator:
    def __init__(self, lookahead_candles=6):  # 6 свечей M5 = 30 минут
        self.lookahead_candles = lookahead_candles
    
    def validate_prediction(self, prediction, current_index, df):
        """
        Проверяет, был ли прогноз точным:
        - BUY: цена поднялась выше entry_price на >= 1.5 * ATR за lookahead_candles
        - SELL: цена упала ниже entry_price на >= 1.5 * ATR за lookahead_candles
        - HOLD: цена не вышла за пределы ±0.5 * ATR (без сильного движения)
        """
        try:
            if prediction["action"] == "HOLD":
                return self._validate_hold(current_index, df)
            
            entry_price = prediction["entry_price"]
            sl = prediction["stop_loss"]
            tp = prediction["take_profit"]
            
            # Проверяем движение цены в lookahead окне
            future_slice = df.iloc[current_index + 1 : current_index + 1 + self.lookahead_candles]
            if future_slice.empty:
                return {"accuracy": "pending", "reason": "not_enough_data"}
            
            high_future = future_slice['high'].max()
            low_future = future_slice['low'].min()
            
            # ATR для текущей свечи (для оценки целей)
            current_atr = df['atr'].iloc[current_index] if 'atr' in df.columns else 0.85
            
            if prediction["action"] == "BUY":
                # Цена достигла TP (или хотя бы 1.5 * ATR вверх)
                target_up = entry_price + (1.5 * current_atr)
                if high_future >= target_up:
                    return {"accuracy": "correct", "movement": "up", "reason": "tp_reached"}
                # Цена упала до SL
                elif low_future <= sl:
                    return {"accuracy": "incorrect", "movement": "down", "reason": "sl_hit"}
                else:
                    # Цена между SL и TP — частичная точность
                    return {"accuracy": "partial", "movement": "neutral", "reason": "no_strong_move"}
            
            elif prediction["action"] == "SELL":
                # Цена упала до TP (или хотя бы 1.5 * ATR вниз)
                target_down = entry_price - (1.5 * current_atr)
                if low_future <= target_down:
                    return {"accuracy": "correct", "movement": "down", "reason": "tp_reached"}
                # Цена поднялась до SL
                elif high_future >= sl:
                    return {"accuracy": "incorrect", "movement": "up", "reason": "sl_hit"}
                else:
                    return {"accuracy": "partial", "movement": "neutral", "reason": "no_strong_move"}
            
            return {"accuracy": "invalid", "reason": "unknown_action"}
            
        except Exception as e:
            # ✅ В случае любой ошибки возвращаем стандартный ответ
            print(f"[VALIDATION ERROR] {str(e)}")
            return {"accuracy": "invalid", "reason": "calculation_failed"}

    def _validate_hold(self, current_index, df):
        """Проверяет, была ли правильная причина для HOLD"""
        try:
            future_slice = df.iloc[current_index + 1 : current_index + 1 + self.lookahead_candles]
            if future_slice.empty:
                return {"accuracy": "pending", "reason": "not_enough_data"}
            
            price_change = abs(future_slice['close'].iloc[-1] - df['close'].iloc[current_index])
            current_atr = df['atr'].iloc[current_index] if 'atr' in df.columns else 0.85
            
            # Если движение было > 1.5 * ATR, но не было сигнала — HOLD был неправильным
            if price_change > (1.5 * current_atr):
                return {"accuracy": "incorrect", "reason": "missed_strong_move"}
            else:
                return {"accuracy": "correct", "reason": "no_significant_move"}
                
        except Exception as e:
            print(f"[VALIDATION ERROR] {str(e)}")
            return {"accuracy": "invalid", "reason": "calculation_failed"}

    def calculate_accuracy_metrics(self, results):
        """Собирает метрики точности"""
        total_predictions = len(results)
        
        # ✅ Добавляем фильтр для безопасного доступа к ключу 'accuracy'
        correct_predictions = len([r for r in results if r.get("accuracy") == "correct"])
        incorrect_predictions = len([r for r in results if r.get("accuracy") == "incorrect"])
        partial_predictions = len([r for r in results if r.get("accuracy") == "partial"])
        
        accuracy_rate = (correct_predictions / total_predictions * 100) if total_predictions > 0 else 0
        precision_buy = self._calculate_precision(results, "BUY")
        precision_sell = self._calculate_precision(results, "SELL")
        
        return {
            "total_predictions": total_predictions,
            "correct_predictions": correct_predictions,
            "incorrect_predictions": incorrect_predictions,
            "partial_predictions": partial_predictions,
            "accuracy_rate": round(accuracy_rate, 2),
            "precision_buy": precision_buy,
            "precision_sell": precision_sell,
            "detailed_results": results
        }

    def _calculate_precision(self, results, action_type):
        """Точность для конкретного типа сигнала (BUY/SELL)"""
        relevant_results = [r for r in results if r.get("prediction", {}).get("action") == action_type]
        if not relevant_results:
            return 0.0
        
        correct = len([r for r in relevant_results if r.get("accuracy") == "correct"])
        return round((correct / len(relevant_results)) * 100, 2)