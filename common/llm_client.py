import json
import logging
import os
import re
from typing import Type, TypeVar
from openai import AsyncOpenAI
from pydantic import BaseModel

logger = logging.getLogger("mas.llm_client")

T = TypeVar("T", bound=BaseModel)


class LLMClient:
    """
    Унифицированный асинхронный клиент для взаимодействия с LLM.
    Гарантирует возврат строго типизированного Pydantic-объекта (Structured Outputs).
    """

    def __init__(self) -> None:
        self.api_key = os.getenv("LLM_API_KEY", "ollama")
        self.base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
        self.model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        self.temperature = float(os.getenv("LLM_TEMPERATURE", "0.1"))

        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

    async def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: Type[T],
    ) -> T:
        """
        Отправляет запрос в LLM и принудительно парсит ответ в заданную Pydantic-схему.
        """
        # Попытка 1: Нативный Structured Outputs (поддерживается OpenAI, Gemini, vLLM, свежей Ollama)
        try:
            completion = await self.client.beta.chat.completions.parse(
                model=self.model,
                temperature=self.temperature,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format=response_model,
            )
            parsed_obj = completion.choices[0].message.parsed
            if parsed_obj is not None:
                return parsed_obj
        except Exception as e:
            logger.warning(
                f"Нативный Structured Output не сработал ({e}). "
                f"Переключение на fallback-режим с JSON-схемой в промпте."
            )

        # Попытка 2 (Fallback): Инжекция JSON-схемы в системный промпт для любых совместимых моделей
        schema_json = json.dumps(response_model.model_json_schema(), ensure_ascii=False, indent=2)
        enriched_system_prompt = (
            f"{system_prompt}\n\n"
            f"КРИТИЧЕСКОЕ ТРЕБОВАНИЕ: Ответь ИСКЛЮЧИТЕЛЬНО валидным JSON-объектом без маркдаун-оберток, "
            f"строго соответствующим следующей JSON Schema:\n{schema_json}"
        )

        response = await self.client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": enriched_system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        raw_content = response.choices[0].message.content or "{}"
        cleaned_json = self._strip_markdown_fences(raw_content)
        return response_model.model_validate_json(cleaned_json)

    @staticmethod
    def _strip_markdown_fences(text: str) -> str:
        """Удаляет возможные обертки ```json ... ``` из ответа модели."""
        text = text.strip()
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return text