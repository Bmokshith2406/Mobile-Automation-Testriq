import asyncio
import inspect

from app.core.config import get_settings

settings = get_settings()

# ----------------------------------------
# Global Gemini concurrency throttle
# ----------------------------------------

GEMINI_MAX_CONCURRENCY = settings.MAX_CONCURRENT_LLM_CALLS

GEMINI_SEMAPHORE = asyncio.Semaphore(GEMINI_MAX_CONCURRENCY)


# ----------------------------------------
# Async-safe wrapper helper
# ----------------------------------------

async def run_gemini_call(func):
    """
    Wrap ANY Gemini call safely with concurrency throttle.

    Supports:
      - sync callables   -> executed in asyncio.to_thread()
      - async callables  -> awaited directly

    Usage:
        response = await run_gemini_call(
                lambda: model.models.generate_content(
                    model=settings.GEMINI_LLM_MODEL,
                    contents=prompt
                )
            )
    """

    async with GEMINI_SEMAPHORE:
        try:
            # If async function
            if inspect.iscoroutinefunction(func):
                return await func()

            # If sync function → run in thread
            return await asyncio.to_thread(func)

        except Exception:
            raise