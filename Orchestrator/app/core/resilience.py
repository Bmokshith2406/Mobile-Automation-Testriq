import time
import asyncio
import logging
from dataclasses import dataclass
from typing import Dict, Optional, Callable, Awaitable, Any
from fastapi import HTTPException, status
from app.core.config import settings
from app.core.metrics import DOWNSTREAM_RETRIES, DOWNSTREAM_FAILURES

logger = logging.getLogger("orchestrator")

# ==============================
# Circuit Breaker (simple in-memory)
# ==============================
@dataclass
class CircuitState:
    failures: int = 0
    last_failure_ts: Optional[float] = None
    open_until: Optional[float] = None

circuit_states: Dict[str, CircuitState] = {}

def is_service_available(service_name: str) -> bool:
    cs = circuit_states.get(service_name)
    if not cs:
        return True
    if cs.open_until and time.time() < cs.open_until:
        return False
    return True

def record_failure(service_name: str) -> None:
    cs = circuit_states.setdefault(service_name, CircuitState())
    cs.failures += 1
    cs.last_failure_ts = time.time()
    if cs.failures >= settings.CIRCUIT_BREAKER_FAILURE_THRESHOLD:
        cs.open_until = time.time() + settings.CIRCUIT_BREAKER_COOLDOWN
        logger.warning(
            "Circuit opened for service %s until %s",
            service_name,
            cs.open_until,
            extra={"request_id": "-"},
        )

def record_success(service_name: str) -> None:
    if service_name in circuit_states:
        del circuit_states[service_name]

async def retry_call(
    name: str,
    coro_factory: Callable[[], Awaitable[Any]],
    attempts: Optional[int] = None,
    backoff_base: Optional[float] = None,
) -> Any:
    """
    Implements retries with exponential backoff + jitter. Raises last exception on permanent failure.
    """
    attempts = attempts or settings.RETRY_ATTEMPTS
    base = backoff_base or settings.RETRY_BACKOFF_BASE

    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            if not is_service_available(name):
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"{name} circuit open",
                )
            return await coro_factory()
        except HTTPException as he:
            # downstream intentionally raised HTTPException (e.g., 5xx returned)
            last_exc = he
            logger.warning(
                "Downstream %s HTTPException attempt %d/%d: %s",
                name,
                attempt,
                attempts,
                getattr(he, "detail", str(he)),
                extra={"request_id": "-"},
            )
            record_failure(name)
            # No backoff on explicitly returned HTTPException, but small sleep helps avoid tight loop
            await asyncio.sleep(base * 0.5)
        except Exception as exc:
            last_exc = exc
            DOWNSTREAM_RETRIES.labels(service=name).inc()
            # jitter in [ -0.05*base , +0.05*base ]
            jitter = (0.1 * base) * (1 + (0.5 - (time.time() % 1)))
            backoff = base * (2 ** (attempt - 1)) + jitter
            logger.exception(
                "Downstream %s exception attempt %d/%d; sleeping %.2fs",
                name,
                attempt,
                attempts,
                backoff,
                extra={"request_id": "-"},
            )
            await asyncio.sleep(backoff)
            record_failure(name)

    # permanent failure
    DOWNSTREAM_FAILURES.labels(service=name).inc()
    if isinstance(last_exc, HTTPException):
        raise last_exc
    raise HTTPException(status_code=500, detail=f"{name} failed after retries: {last_exc}")
