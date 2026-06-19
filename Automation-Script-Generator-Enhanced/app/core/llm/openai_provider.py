# app/core/llm/openai_provider.py
"""
OpenAI LLM Provider Implementation (Fallback)
"""

import logging
from typing import Optional

from app.core.config import get_settings
from app.core.llm.base import (
    BaseLLMProvider,
    LLMProviderType,
    LLMResponse,
    LLMConfig,
)

logger = logging.getLogger("llm.openai")


class OpenAIProvider(BaseLLMProvider):
    """
    OpenAI LLM provider implementation.
    
    Serves as a fallback when primary provider is unavailable.
    Requires 'openai' package to be installed.
    """
    
    def __init__(self, model_name: str = "gpt-4o"):
        settings = get_settings()
        self._api_key = settings.OPENAI_API_KEY
        self._model_name = model_name
        self._client = None
        
        if self._api_key:
            try:
                import openai
                self._client = openai.AsyncOpenAI(api_key=self._api_key)
                logger.info("OpenAIProvider initialized | model=%s", self._model_name)
            except ImportError:
                logger.warning("OpenAI package not installed")
    
    @property
    def provider_type(self) -> LLMProviderType:
        return LLMProviderType.OPENAI
    
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
            max_output_tokens=settings.MAX_OUTPUT_TOKENS,
            timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
        )
        
        try:
            import asyncio

            create_kwargs = dict(
                model=self._model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=config.temperature,
                max_tokens=config.max_output_tokens,
            )
            if config.response_schema is not None:
                create_kwargs["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "result",
                        "schema": config.response_schema,
                        "strict": False,
                    },
                }

            response = await asyncio.wait_for(
                self._client.chat.completions.create(**create_kwargs),
                timeout=config.timeout_seconds,
            )
            
            text = response.choices[0].message.content if response.choices else None
            
            return LLMResponse(
                text=text,
                input_tokens=response.usage.prompt_tokens if response.usage else 0,
                output_tokens=response.usage.completion_tokens if response.usage else 0,
                model=self._model_name,
                finish_reason=response.choices[0].finish_reason if response.choices else "empty",
                raw_response=response,
            )
            
        except Exception as e:
            logger.error("OpenAI API error: %s", str(e))
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
                config=LLMConfig(max_output_tokens=10, timeout_seconds=10),
            )
            return response.text is not None
        except Exception:
            return False

