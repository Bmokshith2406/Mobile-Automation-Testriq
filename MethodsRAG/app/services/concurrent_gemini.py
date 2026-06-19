"""Concurrent Gemini API call execution with proper concurrency limits."""

import asyncio
from typing import Callable, Any, List, Optional
from app.core.config import get_settings
from app.core.logging import logger
from app.core.exceptions import ExternalServiceError

settings = get_settings()

# Global semaphore for limiting concurrent Gemini calls
_gemini_semaphore: Optional[asyncio.Semaphore] = None


def get_gemini_semaphore() -> asyncio.Semaphore:
    """Get or create the Gemini API semaphore."""
    global _gemini_semaphore
    
    if _gemini_semaphore is None:
        max_concurrent = settings.MAX_CONCURRENT_LLM_CALLS
        _gemini_semaphore = asyncio.Semaphore(max_concurrent)
        logger.info(f"Created Gemini semaphore with limit: {max_concurrent}")
    
    return _gemini_semaphore


async def call_gemini_concurrent(
    coroutine: Callable,
    task_name: str = "gemini_call",
) -> Any:
    """
    Execute a Gemini API call with concurrency limiting.
    
    Args:
        coroutine: Async callable that makes the Gemini API call
        task_name: Name for logging/debugging
    
    Returns:
        Result from the coroutine
    
    Raises:
        ExternalServiceError: If the call fails
    """
    semaphore = get_gemini_semaphore()
    
    async with semaphore:
        try:
            logger.debug(f"Starting concurrent Gemini call: {task_name}")
            result = await coroutine()
            logger.debug(f"Completed concurrent Gemini call: {task_name}")
            return result
        except Exception as e:
            logger.error(f"Concurrent Gemini call failed ({task_name}): {e}")
            raise


async def parallel_gemini_calls(
    coroutines: List[tuple[Callable, str]],
) -> List[Any]:
    """
    Execute multiple Gemini API calls in parallel with concurrency limiting.
    
    Args:
        coroutines: List of (coroutine_callable, task_name) tuples
    
    Returns:
        List of results in the same order as input coroutines
    
    Raises:
        ExternalServiceError: If any call fails (partial failure)
    """
    tasks = [
        call_gemini_concurrent(coroutine, task_name)
        for coroutine, task_name in coroutines
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=False)
    return results


async def parallel_gemini_calls_with_timeout(
    coroutines: List[tuple[Callable, str]],
    timeout_seconds: Optional[float] = None,
) -> List[Any]:
    """
    Execute multiple Gemini API calls in parallel with timeout.
    
    Args:
        coroutines: List of (coroutine_callable, task_name) tuples
        timeout_seconds: Timeout for all calls combined
    
    Returns:
        List of results in the same order as input coroutines
    
    Raises:
        asyncio.TimeoutError: If timeout is exceeded
        ExternalServiceError: If any call fails
    """
    if timeout_seconds is None:
        timeout_seconds = settings.GEMINI_TIMEOUT * 3  # Allow more time for parallel calls
    
    try:
        results = await asyncio.wait_for(
            parallel_gemini_calls(coroutines),
            timeout=timeout_seconds
        )
        return results
    except asyncio.TimeoutError:
        logger.error(f"Parallel Gemini calls timed out after {timeout_seconds}s")
        raise


def reset_gemini_semaphore():
    """Reset the semaphore (useful for testing)."""
    global _gemini_semaphore
    _gemini_semaphore = None
    logger.info("Gemini semaphore reset")
