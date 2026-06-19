from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.llm.providers.base import BaseLLMProvider, parse_text_value, post_json


LOG = logging.getLogger(__name__)


class ChatGPTProvider(BaseLLMProvider):
    provider_name = "openai"

    def __init__(self, settings):
        super().__init__(settings)
        self.model_name = settings.OPENAI_MODEL
        self.available = bool(settings.OPENAI_API_KEY and settings.OPENAI_MODEL)
        if not self.available:
            LOG.warning("OpenAI provider selected but OPENAI_API_KEY or OPENAI_MODEL missing.")

    def _build_messages(self, prompt: str, system_prompt: str | None) -> List[Dict[str, str]]:
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages

    def generate_text(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        timeout: float | None = None,
    ) -> str:
        url = f"{self.settings.OPENAI_BASE_URL.rstrip('/')}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.settings.OPENAI_API_KEY}",
        }
        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": self._build_messages(prompt, system_prompt),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        data = post_json(
            url=url,
            headers=headers,
            payload=payload,
            timeout=timeout or self.settings.LLM_TIMEOUT_SECONDS,
        )

        choices = data.get("choices") or []
        if choices:
            message = choices[0].get("message", {}) or {}
            text = parse_text_value(message.get("content"))
            if text:
                return text

            text = parse_text_value(choices[0].get("text"))
            if text:
                return text

        return ""
