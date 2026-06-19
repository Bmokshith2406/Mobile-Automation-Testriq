"""
Resilience patterns: circuit breaker, retries, timeouts for production.
"""

from enum import Enum
from datetime import datetime, timedelta, timezone
import asyncio
from typing import Callable, Any, Optional

from app.core.logging import logger
from app.core.config import get_settings

settings = get_settings()


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Failing, reject requests
    HALF_OPEN = "half_open" # Testing if service recovered


class CircuitBreaker:
    """
    Circuit breaker pattern for external service calls.
    Prevents cascading failures by stopping requests to failing services.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = settings.CIRCUIT_BREAKER_FAILURE_THRESHOLD,
        recovery_timeout: int = settings.CIRCUIT_BREAKER_RECOVERY_TIMEOUT,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.state = CircuitState.CLOSED

    def record_success(self):
        """Record successful call."""
        self.failure_count = 0
        self.state = CircuitState.CLOSED
        self.last_failure_time = None

    def record_failure(self):
        """Record failed call."""
        self.failure_count += 1
        self.last_failure_time = datetime.now(timezone.utc)

        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN

            logger.warning(
                "circuit_breaker_open",
                extra={
                    "service": self.name,
                    "failure_count": self.failure_count,
                },
            )

    def can_execute(self) -> bool:
        """Check if request should be allowed."""

        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:

            # Check if recovery timeout elapsed
            if self.last_failure_time:
                elapsed = (
                    datetime.now(timezone.utc) - self.last_failure_time
                ).total_seconds()

                if elapsed >= self.recovery_timeout:
                    self.state = CircuitState.HALF_OPEN

                    logger.info(
                        "circuit_breaker_half_open",
                        extra={"service": self.name},
                    )

                    return True

            return False

        # HALF_OPEN - allow single request to test recovery
        return True

    async def call(
        self,
        func: Callable,
        *args,
        **kwargs,
    ) -> Any:
        """
        Execute function with circuit breaker protection.
        """
        from app.core.errors import external_api_error

        if not self.can_execute():
            raise external_api_error(
                f"Service '{self.name}' is unavailable (circuit open)"
            )

        try:

            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)

            self.record_success()
            return result

        except Exception as e:
            self.record_failure()

            logger.error(
                "circuit_breaker_failure",
                extra={
                    "service": self.name,
                    "error": str(e),
                },
            )

            raise


class RetryPolicy:
    """Exponential backoff retry policy."""

    def __init__(
        self,
        max_retries: int = settings.MAX_RETRIES,
        backoff_factor: float = settings.RETRY_BACKOFF_FACTOR,
        max_wait: int = settings.RETRY_MAX_WAIT,
    ):
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.max_wait = max_wait

    async def execute(
        self,
        func: Callable,
        *args,
        **kwargs,
    ) -> Any:
        """Execute function with exponential backoff retries."""

        last_exception = None

        for attempt in range(self.max_retries + 1):

            try:

                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)

                return result

            except Exception as e:

                last_exception = e

                if attempt < self.max_retries:

                    wait_time = min(
                        self.backoff_factor ** attempt,
                        self.max_wait,
                    )

                    logger.warning(
                        "retry_attempt",
                        extra={
                            "attempt": attempt + 1,
                            "max_retries": self.max_retries,
                            "wait_seconds": wait_time,
                            "error": str(e),
                        },
                    )

                    await asyncio.sleep(wait_time)

                else:

                    logger.error(
                        "retry_failed",
                        extra={
                            "attempts": self.max_retries + 1,
                            "error": str(e),
                        },
                    )

        raise last_exception


# Global circuit breakers for key services
gemini_breaker = CircuitBreaker("gemini")
mongodb_breaker = CircuitBreaker("mongodb")
embedding_breaker = CircuitBreaker("embedding")