from __future__ import annotations

import logging
from typing import Any, Dict

from app.llm.providers.base import BaseLLMProvider, parse_text_value, post_json


LOG = logging.getLogger(__name__)


class AnthropicProvider(BaseLLMProvider):
    provider_name = "anthropic"

    def __init__(self, settings):
        super().__init__(settings)
        self.model_name = settings.ANTHROPIC_MODEL
        self.available = bool(settings.ANTHROPIC_API_KEY and settings.ANTHROPIC_MODEL)
        if not self.available:
            LOG.warning("Anthropic provider selected but ANTHROPIC_API_KEY or ANTHROPIC_MODEL missing.")

    def generate_text(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        timeout: float | None = None,
    ) -> str:
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.settings.ANTHROPIC_API_KEY or "",
            "anthropic-version": self.settings.ANTHROPIC_VERSION,
        }
        payload: Dict[str, Any] = {
            "model": self.model_name,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        }
        if system_prompt:
            payload["system"] = system_prompt

        data = post_json(
            url=f"{self.settings.ANTHROPIC_BASE_URL.rstrip('/')}/v1/messages",
            headers=headers,
            payload=payload,
            timeout=timeout or self.settings.LLM_TIMEOUT_SECONDS,
        )

        return parse_text_value(data.get("content"))
