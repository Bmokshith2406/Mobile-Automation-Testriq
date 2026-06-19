from __future__ import annotations

import logging

from google import genai

from app.llm.providers.base import BaseLLMProvider


LOG = logging.getLogger(__name__)


class GeminiProvider(BaseLLMProvider):
    provider_name = "gemini"

    def __init__(self, settings):
        super().__init__(settings)
        self.model_name = settings.GEMINI_MODEL
        self._client = None

        api_key = settings.GOOGLE_API_KEY
        if not api_key:
            LOG.warning("Gemini provider selected but GOOGLE_API_KEY missing.")
            return

        try:
            self._client = genai.Client(api_key=api_key)
            self.available = True
        except Exception:
            LOG.exception("Failed to initialize Gemini client")
            raise

    def generate_text(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        timeout: float | None = None,
    ) -> str:
        if not self._client:
            raise RuntimeError("Gemini client unavailable")

        full_prompt = prompt.strip()
        if system_prompt:
            full_prompt = f"{system_prompt.strip()}\n\n{full_prompt}"

        try:
            response = self._client.models.generate_content(
                model=self.model_name,
                contents=full_prompt,
            )
            return (response.text or "").strip()
        except Exception as e:
            exc_str = str(e).lower()
            if ("429" in exc_str or "rate" in exc_str or "quota" in exc_str) and self.model_name == self.settings.GEMINI_MODEL:
                LOG.warning(f"Quota exhausted for {self.model_name}. Switching to fallback {self.settings.LLM_FALLBACK_MODEL}")
                self.model_name = self.settings.LLM_FALLBACK_MODEL
                try:
                    response = self._client.models.generate_content(
                        model=self.model_name,
                        contents=full_prompt,
                    )
                    return (response.text or "").strip()
                except Exception:
                    pass
            raise
        except Exception:
            return ""

    def close(self) -> None:
        try:
            if hasattr(self._client, "close"):
                self._client.close()
        except Exception:
            LOG.exception("Error closing Gemini client")
