import asyncio
import warnings
from app.core.config import get_settings
from app.core.logger import get_logger
from app.services.ai.base import BaseAIProvider

logger = get_logger(__name__)
settings = get_settings()

class GeminiProvider(BaseAIProvider):
    def __init__(self):
        super().__init__()
        # `google-genai` currently emits a noisy import-time Pydantic warning
        # about `<built-in function any>` inside the library's own model
        # definitions. Suppress that specific third-party warning locally so
        # service startup logs stay actionable.
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"<built-in function any> is not a Python type.*",
                category=UserWarning,
                module=r"pydantic\._internal\._generate_schema",
            )
            from google import genai
        api_key = settings.GEMINI_API_KEY.get_secret_value() if settings.GEMINI_API_KEY else None
        if not api_key:
            raise ValueError("GEMINI_API_KEY not configured")
        self.client = genai.Client(api_key=api_key)
        self.model_name = settings.GEMINI_MODEL
        logger.info("Gemini client initialized", extra={"model": self.model_name})
        
    async def _generate(self, prompt: str) -> str:
        try:
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.model_name,
                contents=prompt,
            )
        except Exception as e:
            exc_str = str(e).lower()
            if ("429" in exc_str or "rate" in exc_str or "quota" in exc_str) and self.model_name == settings.GEMINI_MODEL:
                logger.warning(
                    f"Quota exhausted for {self.model_name}. Switching to fallback {settings.LLM_FALLBACK_MODEL}"
                )
                self.model_name = settings.LLM_FALLBACK_MODEL
                response = await asyncio.to_thread(
                    self.client.models.generate_content,
                    model=self.model_name,
                    contents=prompt,
                )
            else:
                raise

        if not response or not response.text:
            raise ValueError("Empty response from Gemini")
        return response.text
