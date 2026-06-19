from __future__ import annotations

from app.core.config import get_settings, resolve_llm_provider
from app.llm.providers.anthropic import AnthropicProvider
from app.llm.providers.base import BaseLLMProvider, NullLLMProvider
from app.llm.providers.chatgpt import ChatGPTProvider
from app.llm.providers.gemini import GeminiProvider
from app.llm.providers.localllm import LocalLLMProvider


PROVIDER_CLASSES = {
    "gemini": GeminiProvider,
    "openai": ChatGPTProvider,
    "anthropic": AnthropicProvider,
    "local": LocalLLMProvider,
}


def build_llm_provider(settings=None) -> BaseLLMProvider:
    current = settings or get_settings()
    provider_name = resolve_llm_provider(current)
    provider_class = PROVIDER_CLASSES.get(provider_name)
    if provider_class is None:
        return NullLLMProvider(current)
    return provider_class(current)


__all__ = [
    "AnthropicProvider",
    "BaseLLMProvider",
    "ChatGPTProvider",
    "GeminiProvider",
    "LocalLLMProvider",
    "NullLLMProvider",
    "build_llm_provider",
]
