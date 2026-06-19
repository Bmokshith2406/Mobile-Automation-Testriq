import asyncio
import logging
import random
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Dict, Optional

from app.core.config import get_settings, resolve_llm_provider
from app.core.resilience import CircuitBreaker
from app.llm.providers import build_llm_provider


settings = get_settings()
LOG = logging.getLogger(__name__)


class LLMClientManager:
    _instance: Optional["LLMClientManager"] = None
    _instance_lock = threading.Lock()

    def __init__(
        self,
        max_concurrency: int = settings.MAX_CONCURRENT_LLM_CALLS,
        max_workers: int = 8,
        retries: int = settings.LLM_RETRIES,
        backoff_base: float = settings.LLM_BACKOFF_BASE_SECONDS,
        rate_limit_per_minute: int = settings.LLM_RATE_LIMIT_PER_MINUTE,
    ):
        self._max_concurrency = max_concurrency
        self._max_workers = max_workers
        self._default_retries = retries
        self._backoff_base = backoff_base
        self._default_timeout = settings.LLM_TIMEOUT_SECONDS
        self._rate_limit_per_minute = rate_limit_per_minute
        self._rate_tokens = rate_limit_per_minute
        self._rate_last_refill = time.time()
        self._rate_lock = threading.Lock()

        self._success_calls = 0
        self._failed_calls = 0
        self._active_calls = 0
        self._total_calls = 0
        self._active_calls_lock = threading.Lock()
        self._async_sem: Optional[asyncio.Semaphore] = None
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._breaker = CircuitBreaker("llm")

        self._provider_client = build_llm_provider(settings)
        provider_name = getattr(self._provider_client, "provider_name", "none")
        self._provider = None if provider_name == "none" else provider_name
        self._available = bool(getattr(self._provider_client, "available", False))
        self._model_name = str(getattr(self._provider_client, "model_name", "") or "")

        if self._provider is None:
            LOG.warning("No LLM provider enabled. LLM-backed features will use fallbacks.")

        LOG.info(
            "LLMClientManager initialized",
            extra={
                "provider": self._provider or "none",
                "available": self._available,
                "max_concurrency": max_concurrency,
                "max_workers": max_workers,
            },
        )

    @classmethod
    def _config_signature(cls) -> tuple[Any, ...]:
        provider = resolve_llm_provider(settings)
        return (
            provider,
            settings.GEMINI_MODEL,
            settings.OPENAI_MODEL,
            settings.OPENAI_BASE_URL,
            settings.ANTHROPIC_MODEL,
            settings.ANTHROPIC_BASE_URL,
            settings.ANTHROPIC_VERSION,
            settings.LOCAL_LLM_MODEL,
            settings.LOCAL_LLM_API_URL,
            settings.LOCAL_LLM_API_FORMAT,
            settings.GOOGLE_API_KEY or "",
            settings.OPENAI_API_KEY or "",
            settings.ANTHROPIC_API_KEY or "",
            settings.LOCAL_LLM_API_KEY or "",
            settings.LOCAL_LLM_EXTRA_HEADERS_JSON or "",
        )

    @classmethod
    def get_instance(cls) -> "LLMClientManager":
        stale_instance: Optional["LLMClientManager"] = None

        with cls._instance_lock:
            current_signature = cls._config_signature()

            existing_signature = None
            if cls._instance is not None:
                existing_signature = getattr(cls._instance, "_config_signature_value", None)

            if cls._instance is not None and existing_signature != current_signature:
                stale_instance = cls._instance
                cls._instance = None

            if cls._instance is None:
                cls._instance = LLMClientManager()
                cls._instance._config_signature_value = current_signature

            instance = cls._instance

        if stale_instance is not None:
            stale_instance.close(wait=False)

        return instance

    @property
    def provider_name(self) -> str | None:
        return self._provider

    @property
    def available(self) -> bool:
        return self._available

    @property
    def model_name(self) -> str:
        return self._model_name

    def _ensure_async_sem(self) -> asyncio.Semaphore:
        if self._async_sem is None:
            with self._instance_lock:
                if self._async_sem is None:
                    self._async_sem = asyncio.Semaphore(self._max_concurrency)
        return self._async_sem

    def _acquire_rate_limit(self) -> None:
        with self._rate_lock:
            now = time.time()
            elapsed = now - self._rate_last_refill
            refill = elapsed * (self._rate_limit_per_minute / 60)
            self._rate_tokens = min(
                self._rate_limit_per_minute,
                self._rate_tokens + refill,
            )
            self._rate_last_refill = now

            if self._rate_tokens < 1:
                sleep_seconds = 1
                LOG.warning(
                    "LLM rate limit reached",
                    extra={"provider": self._provider, "sleep_seconds": sleep_seconds},
                )
                while True:
                    now = time.time()
                    elapsed = now - self._rate_last_refill
                    refill = elapsed * (self._rate_limit_per_minute / 60)
                    self._rate_tokens = min(
                        self._rate_limit_per_minute,
                        self._rate_tokens + refill,
                    )
                    self._rate_last_refill = now
                    if self._rate_tokens >= 1:
                        self._rate_tokens -= 1
                        return
                    time.sleep(sleep_seconds)

            self._rate_tokens -= 1

    def _inc_active(self) -> None:
        with self._active_calls_lock:
            self._active_calls += 1
            self._total_calls += 1

    def _dec_active(self) -> None:
        with self._active_calls_lock:
            self._active_calls = max(0, self._active_calls - 1)

    def _backoff_sleep(self, attempt: int) -> None:
        sleep_seconds = min(10, self._backoff_base * (2 ** (attempt - 1)))
        sleep_seconds *= 0.5 + random.random() * 0.5
        time.sleep(sleep_seconds)

    def _generate_sync(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        timeout: float | None = None,
    ) -> str:
        if not self._available or not self._provider:
            raise RuntimeError("No LLM provider available")

        return self._provider_client.generate_text(
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
        )

    async def generate_text(
        self,
        prompt: str,
        system_prompt: str | None = None,
        retries: Optional[int] = None,
        timeout: Optional[float] = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> str:
        if not self._available:
            raise RuntimeError("LLM provider unavailable")

        if retries is None:
            retries = self._default_retries

        sem = self._ensure_async_sem()
        loop = asyncio.get_running_loop()

        async with _AsyncSemaphoreContext(sem):
            self._inc_active()
            start_time = time.time()
            try:
                attempt = 0
                last_exc = None
                while attempt < retries:
                    attempt += 1

                    if timeout and (time.time() - start_time) > timeout:
                        raise asyncio.TimeoutError("LLM timeout")

                    try:
                        self._acquire_rate_limit()

                        def _wrapped_call():
                            result = self._breaker.call(
                                self._generate_sync,
                                prompt,
                                system_prompt,
                                max_tokens,
                                temperature,
                                timeout,
                            )
                            if asyncio.iscoroutine(result):
                                loop2 = asyncio.new_event_loop()
                                try:
                                    return loop2.run_until_complete(result)
                                finally:
                                    loop2.close()
                            return result

                        future: Future = loop.run_in_executor(self._executor, _wrapped_call)
                        if timeout:
                            remaining = max(timeout - (time.time() - start_time), 0.1)
                            result = await asyncio.wait_for(future, remaining)
                        else:
                            result = await future

                        self._success_calls += 1
                        return result

                    except Exception as exc:
                        last_exc = exc
                        if "429" in str(exc):
                            sleep_seconds = min(30, 2 ** attempt)
                            await asyncio.sleep(sleep_seconds)
                        else:
                            await loop.run_in_executor(None, self._backoff_sleep, attempt)

                self._failed_calls += 1
                raise last_exc
            finally:
                self._dec_active()

    def health(self) -> Dict[str, Any]:
        with self._active_calls_lock:
            active_calls = self._active_calls
            total_calls = self._total_calls

        return {
            "provider": self._provider or "none",
            "model": self.model_name,
            "available": self._available,
            "active_calls": active_calls,
            "total_calls": total_calls,
            "metrics": {
                "success_calls": self._success_calls,
                "failed_calls": self._failed_calls,
            },
        }

    def close(self, wait: bool = True) -> None:
        LOG.info("Shutting down LLM client manager", extra={"provider": self._provider})

        try:
            self._provider_client.close()
        except Exception:
            LOG.exception("Error closing provider client")

        self._executor.shutdown(wait=wait)

        with self._instance_lock:
            if LLMClientManager._instance is self:
                LLMClientManager._instance = None

        self._available = False


class _AsyncSemaphoreContext:
    def __init__(self, sem: asyncio.Semaphore):
        self._sem = sem

    async def __aenter__(self):
        await self._sem.acquire()

    async def __aexit__(self, exc_type, exc, tb):
        self._sem.release()
