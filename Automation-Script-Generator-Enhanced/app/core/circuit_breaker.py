# app/core/circuit_breaker.py
"""
Circuit Breaker Pattern Implementation

Prevents cascading failures by temporarily disabling
failing services and allowing them to recover.
"""

import asyncio
import logging
import time
from enum import Enum
from typing import Optional, Callable, TypeVar, Any
from functools import wraps

from app.core.config import get_settings

logger = logging.getLogger("circuit_breaker")

T = TypeVar("T")


class CircuitState(str, Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreaker:
    """
    Circuit breaker implementation for protecting external services.
    
    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Service failing, requests are rejected immediately
    - HALF_OPEN: Testing if service recovered
    """
    
    def __init__(
        self,
        name: str,
        failure_threshold: Optional[int] = None,
        recovery_timeout: Optional[int] = None,
    ):
        settings = get_settings()
        
        self.name = name
        self.failure_threshold = failure_threshold or settings.CIRCUIT_BREAKER_FAILURE_THRESHOLD
        self.recovery_timeout = recovery_timeout or settings.CIRCUIT_BREAKER_RECOVERY_TIMEOUT
        
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: Optional[float] = None
        self._lock = asyncio.Lock()
        
        logger.info(
            "CircuitBreaker created | name=%s | threshold=%d | recovery=%ds",
            name,
            self.failure_threshold,
            self.recovery_timeout,
        )
    
    @property
    def state(self) -> CircuitState:
        """Current circuit state."""
        return self._state
    
    @property
    def is_closed(self) -> bool:
        """Check if circuit is in closed (normal) state."""
        return self._state == CircuitState.CLOSED
    
    @property
    def is_open(self) -> bool:
        """Check if circuit is open (failing)."""
        return self._state == CircuitState.OPEN
    
    async def can_execute(self) -> bool:
        """
        Check if a request can be executed.
        
        Returns:
            True if request should proceed, False if circuit is open
        """
        async with self._lock:
            if self._state == CircuitState.CLOSED:
                return True
            
            if self._state == CircuitState.OPEN:
                # Check if recovery timeout has passed
                if self._last_failure_time and \
                   time.time() - self._last_failure_time >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    logger.info("CircuitBreaker %s entering HALF_OPEN state", self.name)
                    return True
                return False
            
            # HALF_OPEN - allow one request to test
            return True
    
    async def record_success(self) -> None:
        """Record a successful operation."""
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._last_failure_time = None
                logger.info("CircuitBreaker %s CLOSED (recovered)", self.name)
            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success
                self._failure_count = 0
    
    async def record_failure(self, permanent: bool = False) -> None:
        """Record a failed operation.

        Args:
            permanent: If True the failure is a non-retriable error (e.g. 401
                       invalid API key).  Permanent failures open the circuit
                       immediately regardless of threshold so the service does
                       not waste calls on a misconfigured provider.
        """
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                logger.warning(
                    "CircuitBreaker %s OPEN (recovery failed)",
                    self.name,
                )
            elif self._state == CircuitState.CLOSED:
                if permanent or self._failure_count >= self.failure_threshold:
                    self._state = CircuitState.OPEN
                    reason = "permanent error" if permanent else f"threshold reached: {self._failure_count} failures"
                    logger.warning(
                        "CircuitBreaker %s OPEN (%s)",
                        self.name,
                        reason,
                    )
    
    def get_status(self) -> dict:
        """Get circuit breaker status for monitoring."""
        return {
            "name": self.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
            "last_failure": self._last_failure_time,
        }


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open."""
    pass


def is_permanent_error(exc: Exception) -> bool:
    """Return True for errors that should immediately open the circuit.

    Permanent errors are non-retriable: wrong API key, account suspended,
    invalid request format. Transient errors (timeouts, 429, 5xx) are not
    permanent and should only open the circuit after threshold is hit.
    """
    msg = str(exc).lower()
    permanent_markers = (
        "invalid api key",
        "api_key_invalid",
        "unauthorized",
        "permission_denied",
        "quota_exceeded",
        "billing",
        "account_disabled",
        "invalid_argument",
        "not_found",
    )
    if any(m in msg for m in permanent_markers):
        return True
    # HTTP 4xx except 429 (rate limit) are permanent
    for code in ("400", "401", "403", "404"):
        if code in msg:
            return True
    return False


def with_circuit_breaker(circuit: CircuitBreaker):
    """
    Decorator to wrap async functions with circuit breaker protection.
    
    Args:
        circuit: CircuitBreaker instance to use
        
    Usage:
        @with_circuit_breaker(llm_circuit)
        async def call_llm(prompt: str) -> str:
            ...
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            if not await circuit.can_execute():
                raise CircuitBreakerError(
                    f"Circuit breaker '{circuit.name}' is OPEN"
                )
            
            try:
                result = await func(*args, **kwargs)
                await circuit.record_success()
                return result
            except CircuitBreakerError:
                raise
            except Exception as e:
                await circuit.record_failure(permanent=is_permanent_error(e))
                raise
        
        return wrapper
    return decorator


# Global circuit breakers
_llm_circuit: Optional[CircuitBreaker] = None


def get_llm_circuit_breaker() -> CircuitBreaker:
    """Get or create the LLM circuit breaker."""
    global _llm_circuit
    
    if _llm_circuit is None:
        settings = get_settings()
        if settings.CIRCUIT_BREAKER_ENABLED:
            _llm_circuit = CircuitBreaker(
                name="llm",
                failure_threshold=settings.CIRCUIT_BREAKER_FAILURE_THRESHOLD,
                recovery_timeout=settings.CIRCUIT_BREAKER_RECOVERY_TIMEOUT,
            )
        else:
            # Create a disabled circuit breaker (always closed)
            _llm_circuit = CircuitBreaker(
                name="llm_disabled",
                failure_threshold=999999,
                recovery_timeout=1,
            )
    
    return _llm_circuit

