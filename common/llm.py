"""OpenAI-compatible structured generation with bounded, explicit fallback."""
import json
import logging
import os
import re
from typing import TypeVar

from openai import AsyncOpenAI, BadRequestError
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)
logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self) -> None:
        self.model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        self.temperature = float(os.getenv("LLM_TEMPERATURE", "0.1"))
        self.mode = os.getenv("LLM_OUTPUT_MODE", "auto")
        if self.mode not in {"auto", "json", "prompt"}:
            raise ValueError("LLM_OUTPUT_MODE must be auto, json or prompt")
        self.client = AsyncOpenAI(
            api_key=os.getenv("LLM_API_KEY", "ollama"),
            base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
            timeout=float(os.getenv("LLM_TIMEOUT", "90")),
            max_retries=1,
        )

    async def close(self) -> None:
        await self.client.close()

    async def generate_structured(
        self, system_prompt: str, user_prompt: str, response_model: type[T]
    ) -> T:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        if self.mode == "auto":
            try:
                response = await self.client.beta.chat.completions.parse(
                    model=self.model, temperature=self.temperature,
                    messages=messages, response_format=response_model,
                )
                message = response.choices[0].message
                if message.refusal:
                    raise ValueError("LLM refused structured generation")
                if message.parsed is None:
                    raise ValueError("LLM returned no structured object")
                return message.parsed
            except BadRequestError as exc:
                detail = str(exc).lower()
                if not any(word in detail for word in ("response_format", "json_schema", "structured output")):
                    raise
                logger.info("Provider rejected JSON Schema; trying JSON mode")

        schema = json.dumps(response_model.model_json_schema(), ensure_ascii=False)
        messages[0]["content"] += "\nReturn only a JSON object matching this JSON Schema:\n" + schema
        kwargs = {} if self.mode == "prompt" else {"response_format": {"type": "json_object"}}
        response = await self.client.chat.completions.create(
            model=self.model, temperature=self.temperature, messages=messages, **kwargs,
        )
        if not response.choices or response.choices[0].finish_reason != "stop":
            raise ValueError("LLM returned incomplete output")
        message = response.choices[0].message
        if message.refusal or not message.content:
            raise ValueError("LLM refused or returned empty output")
        return response_model.model_validate_json(self._strip_markdown_fences(message.content))

    @staticmethod
    def _strip_markdown_fences(text: str) -> str:
        match = re.fullmatch(r"\s*```(?:json)?\s*([\s\S]*?)\s*```\s*", text)
        return match.group(1).strip() if match else text.strip()
