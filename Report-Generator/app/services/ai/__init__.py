from fastapi import Request

from app.core.config import get_settings
from app.core.logger import get_logger
from app.services.ai.base import BaseAIProvider


logger = get_logger(__name__)
settings = get_settings()


class NoOpAIProvider(BaseAIProvider):
    """Fallback provider that keeps report generation available without AI."""

    async def _generate(self, prompt: str) -> str:
        return ""

    async def generate_step_summary(self, step_intent: str, step_status: str, duration: float) -> str:
        return ""

    async def generate_overall_description(
        self,
        total_steps: int,
        passed_steps: int,
        failed_steps: int,
        duration_sec: float,
    ) -> str:
        return ""

    async def enrich_steps_with_summaries(self, steps: list) -> dict:
        return {}


def build_ai_service() -> BaseAIProvider:
    if not settings.AI_ENABLED:
        logger.info("AI enrichment disabled; using no-op provider")
        return NoOpAIProvider()

    provider = settings.LLM_PROVIDER.lower()

    if provider == "openai":
        from app.services.ai.openai import OpenAIProvider

        return OpenAIProvider()
    if provider == "anthropic":
        from app.services.ai.anthropic import AnthropicProvider

        return AnthropicProvider()

    from app.services.ai.gemini import GeminiProvider

    return GeminiProvider()


def get_ai_service(request: Request) -> BaseAIProvider:
    provider = getattr(request.app.state, "ai_service", None)
    if provider is None:
        provider = build_ai_service()
        request.app.state.ai_service = provider
    return provider


AIService = BaseAIProvider
