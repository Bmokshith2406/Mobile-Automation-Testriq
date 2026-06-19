# app/core/llm/provider_factory.py
"""
LLM Provider Factory

Creates and manages LLM provider instances with fallback support.
"""

import logging
from typing import Optional, List

from app.core.config import get_settings
from app.core.llm.base import BaseLLMProvider, LLMProviderType
from app.core.llm.gemini_provider import GeminiProvider
from app.core.llm.openai_provider import OpenAIProvider

logger = logging.getLogger("llm.factory")

_primary_provider: Optional[BaseLLMProvider] = None
_fallback_providers: List[BaseLLMProvider] = []


class LLMProviderFactory:
    """
    Factory for creating and managing LLM providers.
    
    Supports:
    - Primary provider configuration
    - Automatic fallback chain
    - Singleton pattern for efficiency
    """
    
    @staticmethod
    def create_provider(
        provider_type: LLMProviderType,
        model_name: Optional[str] = None,
    ) -> BaseLLMProvider:
        """
        Create a specific LLM provider instance.
        
        Args:
            provider_type: Type of provider to create
            model_name: Optional model name override
            
        Returns:
            Configured LLM provider instance
        """
        if provider_type == LLMProviderType.GEMINI:
            return GeminiProvider(model_name=model_name)
        elif provider_type == LLMProviderType.OPENAI:
            return OpenAIProvider(model_name=model_name or "gpt-4o")
        elif provider_type == LLMProviderType.ANTHROPIC:
            # Placeholder for Anthropic implementation
            raise NotImplementedError("Anthropic provider not yet implemented")
        else:
            raise ValueError(f"Unknown provider type: {provider_type}")
    
    @staticmethod
    def get_available_providers(model_name: Optional[str] = None) -> List[BaseLLMProvider]:
        """
        Get list of all available (configured) providers.
        
        Returns:
            List of available provider instances
        """
        providers = []
        
        gemini = GeminiProvider(model_name=model_name)
        if gemini.is_available:
            providers.append(gemini)
        
        openai = OpenAIProvider(model_name=model_name)
        if openai.is_available:
            providers.append(openai)
        
        return providers
    
    @staticmethod
    def initialize_providers() -> tuple[Optional[BaseLLMProvider], List[BaseLLMProvider]]:
        """
        Initialize primary and fallback providers based on configuration.
        
        Returns:
            Tuple of (primary_provider, fallback_providers)
        """
        global _primary_provider, _fallback_providers
        
        settings = get_settings()
        
        # Create primary provider
        try:
            _primary_provider = LLMProviderFactory.create_provider(
                LLMProviderType(settings.LLM_PROVIDER),
                model_name=settings.PRIMARY_MODEL,
            )
            
            if not _primary_provider.is_available:
                logger.warning(
                    "Primary provider %s not available",
                    settings.LLM_PROVIDER,
                )
                _primary_provider = None
        except Exception as e:
            logger.error("Failed to create primary provider: %s", e)
            _primary_provider = None
        
        # Create fallback providers
        _fallback_providers = []
        
        # 1. Add same-provider fallback (e.g. gemini-2.5-flash)
        if _primary_provider and settings.FALLBACK_MODEL and settings.FALLBACK_MODEL != settings.PRIMARY_MODEL:
            try:
                same_provider_fallback = LLMProviderFactory.create_provider(
                    LLMProviderType(settings.LLM_PROVIDER),
                    model_name=settings.FALLBACK_MODEL,
                )
                if same_provider_fallback.is_available:
                    _fallback_providers.append(same_provider_fallback)
            except Exception as e:
                logger.error("Failed to create same-provider fallback: %s", e)
                
        # 2. Add other available providers
        available = LLMProviderFactory.get_available_providers(model_name=settings.FALLBACK_MODEL)
        
        for provider in available:
            if _primary_provider and provider.provider_type == _primary_provider.provider_type:
                continue
            _fallback_providers.append(provider)
        
        logger.info(
            "LLM providers initialized | primary=%s | fallbacks=%d",
            _primary_provider.provider_type if _primary_provider else "none",
            len(_fallback_providers),
        )
        
        return (_primary_provider, _fallback_providers)


def get_llm_provider() -> Optional[BaseLLMProvider]:
    """
    Get the primary LLM provider (singleton).
    
    Returns:
        Primary LLM provider or None if not configured
    """
    global _primary_provider
    
    if _primary_provider is None:
        LLMProviderFactory.initialize_providers()
    
    return _primary_provider


def get_fallback_providers() -> List[BaseLLMProvider]:
    """
    Get the list of fallback providers.
    
    Returns:
        List of fallback provider instances
    """
    global _fallback_providers
    
    if not _fallback_providers and _primary_provider is None:
        LLMProviderFactory.initialize_providers()
    
    return _fallback_providers

