# app/core/llm/gemini_provider.py
"""
Google Gemini LLM Provider Implementation
"""

import asyncio
import logging
from typing import Any, Dict, Optional

from google import genai
from google.genai.types import GenerateContentResponse

from app.core.config import get_settings
from app.core.llm.base import (
    BaseLLMProvider,
    LLMProviderType,
    LLMResponse,
    LLMConfig,
)

logger = logging.getLogger("llm.gemini")


def _adapt_schema_for_gemini(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Convert standard JSON Schema to Gemini-compatible format.

    Transforms anyOf nullable patterns → Gemini's nullable property,
    and drops additionalProperties which Gemini does not support.
    """
    if not isinstance(schema, dict):
        return schema

    # Handle anyOf nullable shorthand: anyOf: [{"type": T}, {"type": "null"}]
    if "anyOf" in schema and isinstance(schema["anyOf"], list):
        variants = schema["anyOf"]
        null_present = any(isinstance(v, dict) and v.get("type") == "null" for v in variants)
        non_null = [v for v in variants if isinstance(v, dict) and v.get("type") != "null"]
        if null_present and len(non_null) == 1:
            adapted = _adapt_schema_for_gemini(non_null[0])
            adapted["nullable"] = True
            return adapted

    result: Dict[str, Any] = {}
    for key, value in schema.items():
        if key == "additionalProperties":
            continue
        elif key == "properties" and isinstance(value, dict):
            result[key] = {k: _adapt_schema_for_gemini(v) for k, v in value.items()}
        elif key == "items" and isinstance(value, dict):
            result[key] = _adapt_schema_for_gemini(value)
        else:
            result[key] = value
    return result


class GeminiProvider(BaseLLMProvider):
    """Google Gemini LLM provider implementation."""
    
    def __init__(self, model_name: Optional[str] = None):
        settings = get_settings()
        self._api_key = settings.GOOGLE_API_KEY
        self._model_name = model_name or settings.PRIMARY_MODEL
        self._client = None
        
        if self._api_key:
            self._client = genai.Client(api_key=self._api_key)
            logger.info(
                "GeminiProvider initialized | model=%s",
                self._model_name,
            )
    
    @property
    def provider_type(self) -> LLMProviderType:
        return LLMProviderType.GEMINI
    
    @property
    def is_available(self) -> bool:
        return self._api_key is not None and self._client is not None
    
    async def generate(
        self,
        prompt: str,
        config: Optional[LLMConfig] = None,
    ) -> LLMResponse:
        if not self.is_available:
            return LLMResponse(
                text=None,
                finish_reason="provider_unavailable",
            )
        
        settings = get_settings()
        config = config or LLMConfig(
            temperature=settings.LLM_TEMPERATURE,
            top_p=settings.LLM_TOP_P,
            max_output_tokens=settings.MAX_OUTPUT_TOKENS,
            timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
        )
        
        gen_config: Dict[str, Any] = {
            "temperature": config.temperature,
            "top_p": config.top_p,
            "max_output_tokens": config.max_output_tokens,
        }
        if config.response_schema is not None:
            gen_config["response_mime_type"] = "application/json"
            gen_config["response_schema"] = _adapt_schema_for_gemini(config.response_schema)

        try:
            response = await asyncio.wait_for(
                self._client.aio.models.generate_content(
                    model=self._model_name,
                    contents=prompt,
                    config=gen_config,
                ),
                timeout=config.timeout_seconds,
            )

            text = self._extract_text(response)
            input_tokens, output_tokens = self._extract_usage(response)

            return LLMResponse(
                text=text,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                model=self._model_name,
                finish_reason="success" if text else "empty",
                raw_response=response,
            )

        except asyncio.TimeoutError:
            logger.error("Gemini API timeout after %ss", config.timeout_seconds)
            return LLMResponse(
                text=None,
                model=self._model_name,
                finish_reason="timeout",
            )
        except Exception as e:
            exc_str = str(e).lower()
            if ("429" in exc_str or "rate" in exc_str or "quota" in exc_str) and self._model_name == settings.PRIMARY_MODEL:
                logger.warning(
                    "Quota exhausted for %s. Switching to fallback %s",
                    self._model_name,
                    settings.FALLBACK_MODEL,
                )
                self._model_name = settings.FALLBACK_MODEL
                try:
                    response = await asyncio.wait_for(
                        self._client.aio.models.generate_content(
                            model=self._model_name,
                            contents=prompt,
                            config=gen_config,
                        ),
                        timeout=config.timeout_seconds,
                    )
                    text = self._extract_text(response)
                    input_tokens, output_tokens = self._extract_usage(response)
                    return LLMResponse(
                        text=text,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        model=self._model_name,
                        finish_reason="success" if text else "empty",
                        raw_response=response,
                    )
                except Exception as fallback_err:
                    logger.error("Fallback Gemini API error: %s", str(fallback_err))
                    return LLMResponse(
                        text=None,
                        model=self._model_name,
                        finish_reason=f"error: {str(fallback_err)}",
                    )
            logger.error("Gemini API error: %s", str(e))
            return LLMResponse(
                text=None,
                model=self._model_name,
                finish_reason=f"error: {str(e)}",
            )
    
    async def health_check(self) -> bool:
        if not self.is_available:
            return False
        
        try:
            response = await self.generate(
                "Respond with 'ok'",
                config=LLMConfig(
                    max_output_tokens=10,
                    timeout_seconds=10,
                ),
            )
            return response.text is not None
        except Exception:
            return False
    
    @staticmethod
    def _extract_text(response: GenerateContentResponse) -> Optional[str]:
        if not response or not response.candidates:
            return None
        
        candidate = response.candidates[0]
        content = getattr(candidate, "content", None)
        if not content or not content.parts:
            return None
        
        parts = [
            part.text
            for part in content.parts
            if getattr(part, "text", None)
        ]
        
        return "\n".join(parts).strip() if parts else None
    
    @staticmethod
    def _extract_usage(response: GenerateContentResponse) -> tuple[int, int]:
        usage = getattr(response, "usage_metadata", None)
        if not usage:
            return (0, 0)
        
        input_tokens = getattr(usage, "prompt_token_count", 0) or 0
        output_tokens = getattr(usage, "candidates_token_count", 0) or 0
        
        return (input_tokens, output_tokens)

