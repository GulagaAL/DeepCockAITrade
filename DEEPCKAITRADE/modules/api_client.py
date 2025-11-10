import os
import json
import time
import requests
from config import Config
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

class DeepSeekClient:
    def __init__(self):
        self.config = Config()
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.DEEPSEEK_API_KEY}"
        }
        self.timeout = int(self.config.DEEPSEEK_TIMEOUT)
        
        # ✅ Хранение истории сообщений (контекста)
        self.conversation_history = [
            {
                "role": "system",
                "content": self._get_system_prompt()
            }
        ]
        print(f"[API] Инициализирован клиент. URL: {self.config.DEEPSEEK_API_URL}")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.exceptions.Timeout, requests.exceptions.ConnectionError))
    )
    def get_prediction(self, market_data_json):
        """Отправляет данные в DeepSeek API и возвращает распарсенный прогноз."""
        try:
            # ✅ Конвертируем все булевы значения в строковые перед отправкой
            safe_data = self._serialize_for_api(market_data_json)
            
            # ✅ Добавляем новое сообщение пользователя в историю
            user_message = {
                "role": "user",
                "content": json.dumps(safe_data, ensure_ascii=False)
            }
            self.conversation_history.append(user_message)
            
            # Формируем payload с историей
            payload = {
                "model": self.config.DEEPSEEK_MODEL,
                "messages": self.conversation_history,
                "response_format": {"type": "json_object"},
                "temperature": 0.1,
                "max_tokens": 500
            }
            
            # ✅ Добавим отладочные принты
            print(f"[API SEND] Отправляем {len(self.conversation_history)} сообщений в историю")
            print(f"[API SEND] Текущая цена: {safe_data.get('market_data', {}).get('price_current', 'N/A')}")
            print(f"[API SEND] Текущий индикатор RSI: {safe_data.get('market_data', {}).get('indicators', {}).get('rsi', {}).get('current', 'N/A')}")
            
            start_time = time.time()
            response = requests.post(
                self.config.DEEPSEEK_API_URL,  # Убедитесь, что это правильный URL!
                headers=self.headers,
                json=payload,
                timeout=self.timeout
            )
            latency = time.time() - start_time
            
            print(f"[API] Запрос выполнен за {latency:.2f} сек. Статус: {response.status_code}")
            
            response.raise_for_status()
            response_data = response.json()
            
            # ✅ Покажем, что вернул API
            print(f"[API RECV] Получено {len(response_data.get('choices', []))} вариантов ответа")
            
            # Извлекаем ответ ассистента
            prediction_json = self._extract_prediction(response_data)
            print(f"[API RECV] Прогноз: {prediction_json.get('action', 'N/A')} с уверенностью {prediction_json.get('confidence', 'N/A')}%")
            
            self._validate_prediction(prediction_json)
            
            # ✅ Добавляем ответ ассистента в историю для сохранения контекста
            assistant_message = {
                "role": "assistant",
                "content": json.dumps(prediction_json, ensure_ascii=False)
            }
            self.conversation_history.append(assistant_message)
            
            # ✅ Покажем текущую длину истории
            print(f"[API] История пополнена. Всего сообщений: {len(self.conversation_history)}")
            
            return prediction_json
            
        except requests.exceptions.HTTPError as e:
            print(f"[API ERROR] HTTP ошибка: {e}")
            print(f"Детали ответа: {response.text}")
            raise
        except requests.exceptions.RequestException as e:
            print(f"[API ERROR] Сетевая ошибка: {str(e)}")
            if hasattr(e, 'response') and e.response:
                print(f"Текст ошибки от API: {e.response.text}")
            raise
        except json.JSONDecodeError as e:
            print(f"[API ERROR] Невалидный JSON в ответе: {str(e)}")
            print(f"Ответ API: {response.text}")
            raise
        except Exception as e:
            print(f"[API ERROR] Неожиданная ошибка: {str(e)}")
            raise
    
    def reset_conversation(self):
        """Сбрасывает историю и возвращает к начальному системному промпту"""
        self.conversation_history = [
            {
                "role": "system",
                "content": self._get_system_prompt()
            }
        ]
        print("[API] История сброшена. Следующий запрос будет с чистого листа.")
    
    def _serialize_for_api(self, obj):
        """Конвертирует объекты в JSON-совместимый формат, особенно булевы значения"""
        if isinstance(obj, (bool,)):
            return str(obj).lower()
        elif isinstance(obj, (dict,)):
            return {k: self._serialize_for_api(v) for k, v in obj.items()}
        elif isinstance(obj, (list,)):
            return [self._serialize_for_api(item) for item in obj]
        else:
            return obj
    
    def _get_system_prompt(self):
        """Возвращает системный промпт из файла или конфига"""
        prompt_path = os.path.join(os.path.dirname(__file__), "../system_prompt.txt")
        if os.path.exists(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read()
        return self._default_system_prompt()
    
    def _default_system_prompt(self):
        return """
        # РОЛЬ И ЦЕЛЬ
        Ты — ядро высокочастотной торговой системы для M5-скальпинга. Твоя задача — генерировать сигналы (BUY/SELL/HOLD) с математически обоснованной степенью уверенности (confidence score). Основной принцип: «Лучше пропустить сделку, чем принять рискованное решение». Все расчёты должны включать:  
        — Точное позиционирование через риск-менеджмент  
        — Коррекцию на комиссии и проскальзывание  
        — Учёт текущих позиций в портфеле  
        — Фильтрацию по confidence (минимум 75 для сделки)  
        — Симметричную оценку для BUY/SELL  

        ❗ ВАЖНО: Исторические данные индикаторов (RSI, Stochastic) должны быть предварительно обработаны внешним модулем. Ты получаешь ТОЛЬКО семантические признаки (дивергенция, тренд, перекупленность), а не сырые массивы.

        # ВХОДНЫЕ ДАННЫЕ (JSON, обновление каждые 20 сек)

        {
          "timestamp": "2024-03-15T12:29:30Z",
          "market_data": {
            "price_current": 150.75,
            "candle_current": {
              "open": 150.50,
              "high": 151.00,
              "low": 150.25,
              "close": 150.75
            },
            "volume_current": 50000,
            "indicators": {
              "ema": {
                "fast": 150.6,
                "slow": 149.9,
                "trend_direction": "bullish",
                "crossover_active": "true"
              },
              "rsi": {
                "current": 62.5,
                "trend": "rising",
                "divergence": "none",
                "overbought": "false",
                "oversold": "false"
              },
              "stochastic": {
                "k": 75.1,
                "d": 70.4,
                "overbought": "true",
                "oversold": "false",
                "crossover": "bullish_k_above_d"
              },
              "bollinger": {
                "upper": 152.3,
                "lower": 149.1,
                "bandwidth": 2.13,
                "price_position": "upper_band"
              },
              "atr": {
                "current": 0.85,
                "ma20": 0.75,
                "multiplier": 1.2
              },
              "vwap": 150.2,
              "obv": {
                "trend": "rising",
                "divergence": "none"
              }
            },
            "patterns": {
              "candlestick": ["bullish_engulfing"],
              "support_resistance": ["resistance_151.00_tested"],
              "price_action": ["break_of_structure_bullish"]
            }
          },
          "risk_params": {
            "account_equity": 10000.0,
            "max_risk_per_trade_pct": 1.0,
            "max_exposure_per_asset_pct": 5.0,
            "min_risk_reward": 1.5,
            "volatility_threshold": 2.0
          },
          "instrument_specs": {
            "symbol": "AAPL",
            "asset_class": "equity",
            "tick_value": 0.01,
            "min_order_size": 1,
            "avg_daily_volume": 1500000,
            "margin_requirement": 0
          },
          "current_positions": {
            "AAPL": {
              "direction": "long",
              "quantity": 10,
              "avg_entry": 150.0,
              "unrealized_pnl": 7.5,
              "position_value_pct": 1.5
            }
          },
          "cost_structure": {
            "commission_per_share": 0.005,
            "fixed_commission": 1.0,
            "max_slippage": 0.02
          }
        }

        # АЛГОРИТМ ПРИНЯТИЯ РЕШЕНИЙ

        1. **ПРЕДВАРИТЕЛЬНЫЕ ФИЛЬТРЫ**  
        — Отмени анализ, если:  
        • volume_current < 30% от avg_daily_volume  
        • atr.current > risk_params.volatility_threshold × atr.ma20  
        • current_positions[символ].position_value_pct > max_exposure_per_asset_pct  
        • Обнаружена дивергенция против текущего тренда (например, медвежья дивергенция в бычьем тренде)  
        — Результат: немедленный HOLD с confidence=0 и пояснением в message.

        2. **РАСЧЁТ ТЕХНИЧЕСКИХ УРОВНЕЙ (СИММЕТРИЧНО ДЛЯ BUY/SELL)**  
        a) **Стоп-лосс (SL):**  
        — BUY: `SL = min(candle_current.low, vwap - (atr.current * atr.multiplier)) - max_slippage`  
        — SELL: `SL = max(candle_current.high, vwap + (atr.current * atr.multiplier)) + max_slippage`  
        b) **Тейк-профит (TP):**  
        — BUY: `TP = price_current + (price_current - SL) * min_risk_reward`  
        — SELL: `TP = price_current - (SL - price_current) * min_risk_reward`  
        c) **Скорректированный риск на акцию:**  
        `risk_per_share = |price_current - SL| + commission_per_share + (max_slippage / 2)`  

        3. **РАСЧЁТ ПОЗИЦИИ И RISK/REWARD**  
        a) Максимальный риск в $:  
        `max_risk_usd = account_equity × (max_risk_per_trade_pct / 100)`  
        b) Базовый размер позиции:  
        `position_size = floor(max_risk_usd / risk_per_share)`  
        c) Финальный объём:  
        `final_size = clamp(position_size, min_order_size, max_exposure_limit)`  
        где `max_exposure_limit = (account_equity × max_exposure_per_asset_pct / 100) / price_current`  
        d) Реальный RRR:  
        `actual_rrr = |TP - price_current| / |price_current - SL|`  
        — Если actual_rrr < min_risk_reward → HOLD  

        4. **ОЦЕНКА УВЕРЕННОСТИ (CONFIDENCE SCORE 0-95)**  
        Начальное значение: 50.  
        **Для BUY сигнала:**  
        +25: Чёткий бычий тренд (ema.trend_direction="bullish" + rsi.trend="rising" + obv.trend="rising")  
        +20: Подтверждённый паттерн (≥2 элемента: candlestick + price_action + S&R)  
        +15: RRR ≥ 2.0  
        +10: Объём > 150% от 5-свечного среднего  
        -30: Сигнал против дневного тренда (внешний контекст)  
        -20: ATR > 1.8 × ATR_MA20  
        -15: Цена у сопротивления при попытке BUY  
        **Для SELL сигнала:**  
        +25: Чёткий медвежий тренд (ema.trend_direction="bearish" + rsi.trend="falling" + obv.trend="falling")  
        ... (симметричные штрафы/бонусы)  
        — Максимум 95. Запрещено использовать 100.  

        5. **УЧЁТ ТЕКУЩИХ ПОЗИЦИЙ**  
        — Если позиция СУЩЕСТВУЕТ:  
        • В ТОМ ЖЕ направлении: добавляй позицию ТОЛЬКО если confidence ≥ 85 и итоговый риск ≤ max_exposure_per_asset_pct  
        • В ПРОТИВОПОЛОЖНОМ:  
        1. Закрой текущую позицию по рыночной цене  
        2. Открой новую ТОЛЬКО если confidence ≥ 80 для нового направления  
        • Никакого хеджирования!  
        — Если цена достигла TP/SL текущей позиции → немедленное закрытие вне зависимости от новых сигналов.  

        # ФОРМАТ ВЫВОДА (СТРОГИЙ JSON)

        {
          "action": "BUY" | "SELL" | "HOLD",
          "confidence": 0-95,
          "size": integer,
          "entry_price": float,
          "stop_loss": float,
          "take_profit": float,
          "risk_percent": float,
          "message": "Структурированное обоснование: 1) Направление сигнала и ключевые факторы 2) Расчёт риска и RRR 3) Изменение позиции в портфеле 4) Детали confidence score. Обязательно укажи: ATR/ATR_MA20, объём/avg_daily_volume, текущий убыток/прибыль по активу. На русском, без воды."
        }

        # КРИТИЧЕСКИЕ ПРАВИЛА

        1. Приоритет безопасности:  
        — Если невозможно точно рассчитать SL/TP или RRR → HOLD с confidence=0  
        — Никогда не превышай max_risk_per_trade_pct даже при confidence=95  

        2. Запрещено:  
        — Использовать исторические массивы (history) напрямую — только предобработанные признаки  
        — Открывать сделку при конфликте с дневным трендом (confidence автоматически -30)  
        — Генерировать SELL при наличии длинной позиции без явного закрытия существующей  

        3. Требования к выводу:  
        — Все числовые поля обязательны даже для HOLD (заполняй 0.00)  
        — В message для HOLD укажи:  
        • Какой фильтр сработал (объём, волатильность, RRR)  
        • Текущий риск по активу в портфеле  
        • Конкретные значения ATR/ATR_MA20 и объёма в % от среднего  
        """
    
    def _extract_prediction(self, api_response):
        try:
            content = api_response["choices"][0]["message"]["content"]
            return json.loads(content)
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            raise ValueError(f"Ошибка извлечения прогноза: {str(e)} | Ответ API: {api_response}")
    
    def _validate_prediction(self, prediction):
        required_fields = ["action", "confidence", "size", "entry_price", "stop_loss", "take_profit", "risk_percent", "message"]
        for field in required_fields:
            if field not in prediction:
                raise ValueError(f"Отсутствует обязательное поле в прогнозе: {field}")
        
        if not isinstance(prediction["confidence"], (int, float)) or not (0 <= prediction["confidence"] <= 95):
            raise ValueError("Невалидное значение confidence")
        
        if prediction["action"] not in ["BUY", "SELL", "HOLD"]:
            raise ValueError(f"Неверное действие: {prediction['action']}")