# app/core/llm/base.py
"""
Abstract LLM Provider Interface

Supports multiple LLM backends with consistent interface.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from enum import Enum


class LLMProviderType(str, Enum):
    """Supported LLM providers."""
    GEMINI = "gemini"
    OPENAI = "openai"
    # ANTHROPIC = "anthropic"  # Not yet implemented — placeholder for future use


@dataclass
class LLMResponse:
    """Standardized LLM response container."""
    text: Optional[str]
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    finish_reason: str = ""
    raw_response: Any = None


@dataclass
class LLMConfig:
    """LLM generation configuration."""
    temperature: float = 0.1
    top_p: float = 0.95
    max_output_tokens: int = 2048
    timeout_seconds: int = 60
    response_schema: Optional[Dict[str, Any]] = field(default=None, compare=False)


class BaseLLMProvider(ABC):
    """
    Abstract base class for LLM providers.
    
    All providers must implement the generate method
    with consistent input/output interface.
    """
    
    @property
    @abstractmethod
    def provider_type(self) -> LLMProviderType:
        """Return the provider type."""
        pass
    
    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Check if the provider is properly configured."""
        pass
    
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        config: Optional[LLMConfig] = None,
    ) -> LLMResponse:
        """
        Generate text from the LLM.
        
        Args:
            prompt: The input prompt
            config: Optional generation configuration
            
        Returns:
            LLMResponse containing the generated text and metadata
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """
        Check if the provider is responding.
        
        Returns:
            True if healthy, False otherwise
        """
        pass

