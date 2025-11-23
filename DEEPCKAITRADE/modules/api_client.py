import os
import json
import time
import requests
from DEEPCKAITRADE.config import Config
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from DEEPCKAITRADE.utils.logger import logger


class DeepSeekClient:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.config = Config()
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.DEEPSEEK_API_KEY}"
        }
        self.timeout = int(self.config.DEEPSEEK_TIMEOUT)

        # Системный промпт загружается и отправляется ТОЛЬКО ОДИН РАЗ при первом запуске
        # Дальше - только JSON в user messages, без повторения промпта
        self.system_prompt_sent = False
        self.conversation_history = []
        self.max_history_messages = 15  # Лимит для обрезки

        logger.info(f"[DeepSeek] Клиент инициализирован. Модель: {self.config.DEEPSEEK_MODEL}")
        self._initialized = True

    def _load_system_prompt(self):
        prompt_path = os.path.join(os.path.dirname(__file__), "../system_prompt.txt")
        if os.path.exists(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        # Fallback - вставь сюда свой дефолтный промпт, если файла нет
        logger.warning("[DeepSeek] system_prompt.txt не найден, используется fallback.")
        return """
        # Вставь полный системный промпт сюда, если нужно
        """.strip()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=3, max=15),
        retry=retry_if_exception_type(requests.exceptions.RequestException)
    )
    def get_prediction(self, market_data_json):
        try:
            # === SYSTEM PROMPT — ТОЛЬКО ОДИН РАЗ ===
            if not self.system_prompt_sent:
                system_content = self._load_system_prompt()
                self.system_prompt = {"role": "system", "content": system_content}  # сохраняем отдельно
                self.system_prompt_sent = True
                logger.info("[DeepSeek] Системный промпт загружен (отправляется каждый раз, но кэшируется моделью)")

            # === ОСТАВЛЯЕМ ТОЛЬКО ПОСЛЕДНИЕ 3 СООБЩЕНИЯ (user + assistant) ===
            # Это ~1500–2000 токенов максимум — идеально!
            recent_history = self.conversation_history[-4:]  # последние 3 пары user/assistant

            # === Формируем минимальный контекст ===
            messages_to_send = [self.system_prompt] + recent_history

            # Добавляем текущее сообщение
            user_content = json.dumps(market_data_json, ensure_ascii=False, separators=(',', ':'))  # ультра-компактный JSON
            messages_to_send.append({"role": "user", "content": user_content})

            payload = {
                "model": self.config.DEEPSEEK_MODEL,
                "messages": messages_to_send,
                "response_format": {"type": "json_object"},
                "temperature": 0.1,
                "max_tokens": 600
            }

            # === ЛОГИ ===
            logger.info(f"[DeepSeek → SEND] Отправлено сообщений: {len(messages_to_send)} | "
                        f"Текущий JSON: ~{len(user_content)//4} токенов")

            start = time.time()
            response = requests.post(
                self.config.DEEPSEEK_API_URL,
                headers=self.headers,
                json=payload,
                timeout=self.timeout
            )
            latency = time.time() - start

            response.raise_for_status()
            data = response.json()
            usage = data.get("usage", {})
            logger.info(f"[DeepSeek ← RECV] {latency:.2f}s | "
                        f"Prompt: {usage.get('prompt_tokens', '?')} | "
                        f"Completion: {usage.get('completion_tokens', '?')} токенов")

            content = data["choices"][0]["message"]["content"]
            prediction = json.loads(content)

            # === Обновляем историю (только для будущего) ===
            self.conversation_history.extend([
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": content}
            ])

            logger.info(f"[DeepSeek] {prediction['action']} | conf={prediction['confidence']}% | {latency:.2f}s")
            self._validate_prediction(prediction)
            return prediction

        except Exception as e:
            logger.error(f"[DeepSeek ERROR] {str(e)}")
            if 'response' in locals():
                logger.error(f"Ответ сервера: {response.text[:1000]}")
            raise

    def _estimate_tokens(self, messages):
        """Грубая оценка количества токенов (для логов)"""
        total = 0
        for msg in messages:
            total += len(msg["content"].split()) * 1.3  # грубо
        return int(total)

    def _validate_prediction(self, prediction):
        required = ["action", "confidence", "size", "entry_price", "stop_loss", "take_profit", "risk_percent",
                    "message"]
        for field in required:
            if field not in prediction:
                raise ValueError(f"Missing field in prediction: {field}")
        if not isinstance(prediction["confidence"], (int, float)) or not 0 <= prediction["confidence"] <= 95:
            raise ValueError(f"Invalid confidence: {prediction.get('confidence', 'N/A')}")
        if prediction["action"] not in ["BUY", "SELL", "HOLD"]:
            raise ValueError(f"Invalid action: {prediction.get('action', 'N/A')}")

    def reset_conversation(self):
        self.conversation_history = []
        self.system_prompt_sent = False
        logger.info("[DeepSeek] Conversation reset.")