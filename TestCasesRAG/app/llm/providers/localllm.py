from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from app.llm.providers.base import BaseLLMProvider, parse_text_value, post_json


LOG = logging.getLogger(__name__)


class LocalLLMProvider(BaseLLMProvider):
    provider_name = "local"

    def __init__(self, settings):
        super().__init__(settings)
        self.model_name = settings.LOCAL_LLM_MODEL or settings.OPENAI_MODEL
        self.available = bool(settings.LOCAL_LLM_API_URL)
        if not self.available:
            LOG.warning("Local provider selected but LOCAL_LLM_API_URL missing.")

    def _extra_headers(self) -> Dict[str, str]:
        raw = self.settings.LOCAL_LLM_EXTRA_HEADERS_JSON or ""
        if not raw.strip():
            return {}
        try:
            parsed = json.loads(raw)
            return {str(key): str(value) for key, value in parsed.items()}
        except Exception:
            LOG.warning("Failed to parse LOCAL_LLM_EXTRA_HEADERS_JSON")
            return {}

    def _build_messages(self, prompt: str, system_prompt: str | None) -> List[Dict[str, str]]:
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _generate_anthropic_compatible(
        self,
        prompt: str,
        system_prompt: str | None,
        max_tokens: int,
        temperature: float,
        timeout: float | None,
    ) -> str:
        base_url = self.settings.LOCAL_LLM_API_URL.rstrip("/")
        if base_url.endswith("/v1/messages"):
            base_url = base_url[:-12]

        headers = {
            "Content-Type": "application/json",
            "anthropic-version": self.settings.ANTHROPIC_VERSION,
        }
        if self.settings.LOCAL_LLM_API_KEY:
            headers["x-api-key"] = self.settings.LOCAL_LLM_API_KEY
        headers.update(self._extra_headers())

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
            url=f"{base_url}/v1/messages",
            headers=headers,
            payload=payload,
            timeout=timeout or self.settings.LLM_TIMEOUT_SECONDS,
        )

        return parse_text_value(data.get("content"))

    def _generate_openai_or_generic(
        self,
        prompt: str,
        system_prompt: str | None,
        max_tokens: int,
        temperature: float,
        timeout: float | None,
        flexible_parse: bool,
    ) -> str:
        headers = {
            "Content-Type": "application/json",
        }
        if self.settings.LOCAL_LLM_API_KEY:
            headers["Authorization"] = f"Bearer {self.settings.LOCAL_LLM_API_KEY}"
        headers.update(self._extra_headers())

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": self._build_messages(prompt, system_prompt),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        data = post_json(
            url=self.settings.LOCAL_LLM_API_URL.rstrip("/"),
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

        if flexible_parse:
            for key in ("output_text", "response", "generated_text", "text", "completion"):
                text = parse_text_value(data.get(key))
                if text:
                    return text

            text = parse_text_value(data.get("content"))
            if text:
                return text

        return ""

    def generate_text(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        timeout: float | None = None,
    ) -> str:
        format_name = self.settings.LOCAL_LLM_API_FORMAT
        if format_name == "anthropic":
            return self._generate_anthropic_compatible(
                prompt=prompt,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
            )

        return self._generate_openai_or_generic(
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
            flexible_parse=True,
        )
