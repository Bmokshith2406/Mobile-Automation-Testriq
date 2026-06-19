# app/core/llm_executor.py
"""
Enhanced LLM Executor

Provides a unified interface for LLM operations with:
- Multi-provider support with automatic fallback
- Circuit breaker protection
- Response caching
- Metrics collection
- Proper logging levels
"""

import asyncio
import logging
import time
from typing import Optional
from functools import lru_cache

from app.core.config import get_settings
from app.core.token_tracker import (
    add_input_tokens,
    add_output_tokens,
    get_input_tokens,
    get_output_tokens,
)
from app.core.llm import get_llm_provider, LLMConfig
from app.core.llm.provider_factory import get_fallback_providers
from app.core.circuit_breaker import get_llm_circuit_breaker, is_permanent_error
from app.core.cache import get_llm_cache
from app.core.metrics import get_metrics

logger = logging.getLogger("llm")


class LLMExecutor:
    """
    Enhanced LLM Executor with production-ready features.
    """

    def __init__(self):

        settings = get_settings()

        # Store the limit; the Semaphore is created lazily inside run()
        # to ensure it is always bound to the running event loop.
        self._max_concurrent = settings.MAX_CONCURRENT_LLM_CALLS
        self._semaphore: Optional[asyncio.Semaphore] = None

        self._provider = get_llm_provider()
        self._fallback_providers = get_fallback_providers()
        self._circuit_breaker = get_llm_circuit_breaker()
        self._cache = get_llm_cache()
        self._metrics = get_metrics()

        self._retries = settings.LLM_DEFAULT_RETRIES
        self._rate_limit_sleep = settings.LLM_RATE_LIMIT_SLEEP

        logger.info(
            "LLMExecutor initialized | provider=%s | fallbacks=%d | concurrency=%d",
            self._provider.provider_type if self._provider else "none",
            len(self._fallback_providers),
            self._max_concurrent,
        )

    def _get_semaphore(self) -> asyncio.Semaphore:
        """
        Return the concurrency semaphore, creating it lazily on first call.

        Must be called from within a running asyncio event loop so the
        Semaphore is bound to the correct loop (Python 3.10+ requirement).
        """
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._max_concurrent)
        return self._semaphore


    async def run(
        self,
        prompt: str,
        *,
        purpose: str,
        use_cache: bool = True,
        config: Optional[LLMConfig] = None,
    ) -> Optional[str]:

        start_time = time.perf_counter()
        input_tokens_before = get_input_tokens()
        output_tokens_before = get_output_tokens()

        logger.info(
            "LLM request | purpose=%s | prompt_chars=%d | cache=%s",
            purpose,
            len(prompt),
            use_cache,
        )

        # ---------- CACHE ----------
        if use_cache:
            cached_response = await self._cache.get(prompt, purpose)
            if cached_response is not None:
                duration_ms = (time.perf_counter() - start_time) * 1000
                self._metrics.record_llm_call(
                    success=True,
                    duration_ms=duration_ms,
                    cached=True,
                )

                logger.info(
                    "LLM cache hit | purpose=%s | duration_ms=%.2f",
                    purpose,
                    duration_ms,
                )

                logger.info(
                    "LLM response (cache) | purpose=%s | chars=%d",
                    purpose,
                    len(cached_response),
                )

                logger.debug("LLM raw response cache (first 200 chars): %.200s", cached_response)

                return cached_response

        # ---------- CIRCUIT BREAKER ----------
        if not await self._circuit_breaker.can_execute():
            logger.warning("LLM circuit breaker OPEN | purpose=%s", purpose)
            return await self._try_fallbacks(prompt, purpose, config)

        # ---------- EXECUTION ----------
        async with self._get_semaphore():
            result = await self._execute_with_retries(prompt, purpose, config)

        duration_ms = (time.perf_counter() - start_time) * 1000

        if result:
            input_delta = get_input_tokens() - input_tokens_before
            output_delta = get_output_tokens() - output_tokens_before
            self._metrics.record_llm_call(
                success=True,
                duration_ms=duration_ms,
                input_tokens=input_delta,
                output_tokens=output_delta,
            )

            if use_cache:
                await self._cache.set(prompt, purpose, result)

            logger.info(
                "LLM success | purpose=%s | chars=%d | duration_ms=%.2f",
                purpose,
                len(result),
                duration_ms,
            )
        else:
            self._metrics.record_llm_call(
                success=False,
                duration_ms=duration_ms,
            )
            logger.warning("LLM failed | purpose=%s", purpose)

        return result

    async def _execute_with_retries(
        self,
        prompt: str,
        purpose: str,
        config: Optional[LLMConfig],
    ) -> Optional[str]:

        if not self._provider:
            return await self._try_fallbacks(prompt, purpose, config)

        for attempt in range(1, self._retries + 2):
            try:
                logger.info(
                    "LLM attempt %d/%d | purpose=%s",
                    attempt,
                    self._retries + 1,
                    purpose,
                )

                response = await self._provider.generate(prompt, config)

                if response.text:
                    add_input_tokens(response.input_tokens)
                    add_output_tokens(response.output_tokens)

                    logger.info(
                        "LLM response | provider=%s | purpose=%s | chars=%d",
                        self._provider.provider_type,
                        purpose,
                        len(response.text),
                    )

                    logger.debug("LLM raw response (first 200 chars): %.200s", response.text)
                    await self._circuit_breaker.record_success()
                    return response.text

                if attempt <= self._retries and self._is_retriable_response(response.finish_reason):
                    await asyncio.sleep(self._rate_limit_sleep)
                    continue

            except Exception as e:
                logger.warning(
                    "LLM error | purpose=%s | attempt=%d | error=%s",
                    purpose,
                    attempt,
                    str(e),
                )

                permanent = is_permanent_error(e)
                if permanent:
                    await self._circuit_breaker.record_failure(permanent=True)
                    break

                if attempt <= self._retries and self._is_retriable(e):
                    sleep_secs = self._parse_retry_after(e) or self._rate_limit_sleep
                    await asyncio.sleep(sleep_secs)
                    continue

                await self._circuit_breaker.record_failure(permanent=False)

        return await self._try_fallbacks(prompt, purpose, config)

    async def _try_fallbacks(
        self,
        prompt: str,
        purpose: str,
        config: Optional[LLMConfig],
    ) -> Optional[str]:

        for provider in self._fallback_providers:
            try:
                logger.info(
                    "Trying fallback provider | type=%s | purpose=%s",
                    provider.provider_type,
                    purpose,
                )

                response = await provider.generate(prompt, config)

                if response.text:
                    add_input_tokens(response.input_tokens)
                    add_output_tokens(response.output_tokens)

                    logger.info(
                        "LLM response (fallback) | provider=%s | purpose=%s | chars=%d",
                        provider.provider_type,
                        purpose,
                        len(response.text),
                    )

                    logger.debug("LLM raw response fallback (first 200 chars): %.200s", response.text)

                    return response.text

            except Exception as e:
                logger.warning(
                    "Fallback provider failed | type=%s | error=%s",
                    provider.provider_type,
                    str(e),
                )

        return None

    @staticmethod
    def _parse_retry_after(exc: Exception) -> Optional[float]:
        """Extract Retry-After seconds from a 429 exception if present."""
        try:
            # httpx / requests-style response attribute
            response = getattr(exc, "response", None)
            if response is None:
                return None
            headers = getattr(response, "headers", {})
            value = headers.get("retry-after") or headers.get("Retry-After")
            if value is not None:
                secs = float(value)
                # Clamp to sane bounds (0.5s – 30s)
                return min(max(secs, 0.5), 30.0)
        except Exception:
            pass
        return None

    @staticmethod
    def _is_retriable(exc: Exception) -> bool:
        if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
            return True

        msg = str(exc).lower()
        return any(
            p in msg
            for p in (
                "rate",
                "timeout",
                "temporar",
                "429",
                "unavailable",
                "resource_exhausted",
                "overloaded",
            )
        )

    @staticmethod
    def _is_retriable_response(reason: str) -> bool:
        if not reason:
            return False
        return any(
            marker in reason.lower()
            for marker in (
                "rate",
                "timeout",
                "temporar",
                "429",
                "unavailable",
                "resource_exhausted",
                "overloaded",
            )
        )

    async def health_check(self) -> dict:
        result = {
            "primary_provider": None,
            "fallback_providers": [],
            "circuit_breaker": self._circuit_breaker.get_status(),
            "cache": self._cache.get_stats(),
        }

        if self._provider:
            result["primary_provider"] = {
                "type": self._provider.provider_type.value,
                "available": self._provider.is_available,
                "healthy": await self._provider.health_check()
                if self._provider.is_available
                else False,
            }

        for provider in self._fallback_providers:
            result["fallback_providers"].append(
                {
                    "type": provider.provider_type.value,
                    "available": provider.is_available,
                }
            )

        return result

@lru_cache
def get_llm_executor() -> LLMExecutor:
    return LLMExecutor()

