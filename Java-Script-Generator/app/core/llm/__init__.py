# app/core/llm/__init__.py
"""
LLM Provider Module

Provides a unified interface for multiple LLM backends
with automatic fallback support.
"""

from app.core.llm.base import (
    BaseLLMProvider,
    LLMProviderType,
    LLMResponse,
    LLMConfig,
)
from app.core.llm.gemini_provider import GeminiProvider
from app.core.llm.openai_provider import OpenAIProvider
from app.core.llm.provider_factory import LLMProviderFactory, get_llm_provider

__all__ = [
    "BaseLLMProvider",
    "LLMProviderType",
    "LLMResponse",
    "LLMConfig",
    "GeminiProvider",
    "OpenAIProvider",
    "LLMProviderFactory",
    "get_llm_provider",
]

