import asyncio
import random
from abc import ABC, abstractmethod
from typing import Dict, List

from app.core.logger import get_logger
from app.core.errors import (
    APIException,
    ErrorCode,
    ErrorCategory,
    ErrorSeverity,
)
from app.core.config import get_settings
from app.models.domain import StepExecution

logger = get_logger(__name__)
settings = get_settings()

class BaseAIProvider(ABC):
    """Abstract Base Class for AI providers (Gemini, OpenAI, Anthropic)."""
    
    def __init__(self):
        self.max_retries = settings.AI_MAX_RETRIES
        self.timeout_seconds = settings.AI_TIMEOUT_SECONDS
        self.max_concurrency = settings.AI_MAX_CONCURRENCY
        self.semaphore = asyncio.Semaphore(self.max_concurrency)

    async def close(self) -> None:
        """Provider cleanup hook."""
        return None
        
    @abstractmethod
    async def _generate(self, prompt: str) -> str:
        """Provider specific generation logic."""
        pass
        
    async def generate_with_retries(self, prompt: str) -> str:
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                text = await asyncio.wait_for(
                    self._generate(prompt),
                    timeout=self.timeout_seconds
                )
                return text.strip()
            except asyncio.TimeoutError as exc:
                last_error = exc
                logger.warning(
                    "AI request timed out on attempt %s after %ss",
                    attempt,
                    self.timeout_seconds,
                    extra={"attempt": attempt},
                )
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "AI generation attempt %s failed: %s",
                    attempt,
                    exc,
                    extra={"attempt": attempt, "error": str(exc)},
                )
            
            if attempt < self.max_retries:
                await asyncio.sleep((2 ** attempt) + random.random())
                
        raise APIException(
            error_code=ErrorCode.AI_PROVIDER_ERROR,
            message="AI generation failed after multiple attempts",
            status_code=502,
            category=ErrorCategory.DEPENDENCY,
            severity=ErrorSeverity.ERROR,
            retryable=True,
            details={"error": str(last_error)},
        )

    async def generate_step_summary(self, step_intent: str, step_status: str, duration: float) -> str:
        prompt = f"""You are an automation reporting assistant.
Write a clear step execution summary in 1–2 sentences of 30-40 words.
Constraints: Maximum 40 words, describe what the step attempted and outcome, be factual and concise, no emojis/markdown/headings/commentary.

Step Data:
Intent: {step_intent}
Status: {step_status}
Execution Time: {duration:.2f} seconds

Return only the summary sentence."""
        return await self.generate_with_retries(prompt)
        
    async def generate_overall_description(self, total_steps: int, passed_steps: int, failed_steps: int, duration_sec: float) -> str:
        prompt = f"""You are an expert test automation reporter.
Write a professional narrative (40–50 words) summarizing the execution flow.
Data:
- Total steps: {total_steps}
- Passed: {passed_steps}
- Failed: {failed_steps}
- Total duration: {duration_sec:.2f} seconds

Rules: Narrative tone, no bullet points, no emojis/markdown/headings/commentary.
Return only the narrative."""
        return await self.generate_with_retries(prompt)
        
    async def enrich_steps_with_summaries(self, steps: List[StepExecution]) -> Dict[str, str]:
        results: Dict[str, str] = {}

        async def enrich(step: StepExecution):
            async with self.semaphore:
                if not step.summary.step_index:
                    return
                ai_text = await self.generate_step_summary(
                    step_intent=step.summary.intent,
                    step_status=step.summary.status,
                    duration=step.summary.duration_sec,
                )
                results[step.summary.step_index] = ai_text
                step.ai_summary = ai_text  # Mutate the model directly
                
        await asyncio.gather(*(enrich(step) for step in steps))
        return results
