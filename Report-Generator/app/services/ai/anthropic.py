from app.core.config import get_settings
from app.core.logger import get_logger
from app.services.ai.base import BaseAIProvider

logger = get_logger(__name__)
settings = get_settings()

class AnthropicProvider(BaseAIProvider):
    def __init__(self):
        super().__init__()
        from anthropic import AsyncAnthropic
        api_key = settings.ANTHROPIC_API_KEY.get_secret_value() if settings.ANTHROPIC_API_KEY else None
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not configured")
        self.client = AsyncAnthropic(api_key=api_key)
        self.model_name = settings.ANTHROPIC_MODEL
        logger.info("Anthropic client initialized", extra={"model": self.model_name})
        
    async def _generate(self, prompt: str) -> str:
        response = await self.client.messages.create(
            model=self.model_name,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}]
        )
        if not response.content:
            raise ValueError("Empty response from Anthropic")
        return response.content[0].text

    async def close(self) -> None:
        close_method = getattr(self.client, "close", None)
        if close_method is not None:
            result = close_method()
            if hasattr(result, "__await__"):
                await result
