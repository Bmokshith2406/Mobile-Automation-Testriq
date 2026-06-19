from app.core.config import get_settings
from app.core.logger import get_logger
from app.services.ai.base import BaseAIProvider

logger = get_logger(__name__)
settings = get_settings()

class OpenAIProvider(BaseAIProvider):
    def __init__(self):
        super().__init__()
        from openai import AsyncOpenAI
        api_key = settings.OPENAI_API_KEY.get_secret_value() if settings.OPENAI_API_KEY else None
        if not api_key:
            raise ValueError("OPENAI_API_KEY not configured")
        self.client = AsyncOpenAI(api_key=api_key)
        self.model_name = settings.OPENAI_MODEL
        logger.info("OpenAI client initialized", extra={"model": self.model_name})
        
    async def _generate(self, prompt: str) -> str:
        response = await self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=256
        )
        if not response.choices:
            raise ValueError("Empty response from OpenAI")
        return response.choices[0].message.content

    async def close(self) -> None:
        await self.client.close()
