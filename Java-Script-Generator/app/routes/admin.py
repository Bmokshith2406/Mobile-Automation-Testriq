# app/routes/admin.py
"""
Admin Operations API

Protected endpoints for operators:
- Cache management (clear, stats)
- Circuit breaker control (reset, status)
- Active batch inspection
- Config introspection (non-sensitive)

All endpoints require the API key.
"""

import hmac
import logging
from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security import APIKeyHeader

from app.core.cache import get_llm_cache
from app.core.circuit_breaker import get_llm_circuit_breaker, CircuitState
from app.core.config import get_settings
from app.core.metrics import get_metrics

router = APIRouter()
logger = logging.getLogger("api.admin")


def _require_api_key(
    api_key: str = Security(APIKeyHeader(name="X-API-Key", auto_error=False)),
) -> None:
    settings = get_settings()
    if not settings.API_KEY_ENABLED:
        return
    if not api_key or not hmac.compare_digest(api_key, settings.API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# ==========================================================
# CACHE
# ==========================================================

@router.get(
    "/cache/stats",
    summary="Cache statistics",
    dependencies=[Depends(_require_api_key)],
)
async def cache_stats() -> Dict[str, Any]:
    """Return LLM response cache hit/miss statistics."""
    cache = get_llm_cache()
    return cache.get_stats()


@router.post(
    "/cache/clear",
    summary="Clear LLM cache",
    dependencies=[Depends(_require_api_key)],
)
async def clear_cache() -> Dict[str, Any]:
    """Evict all cached LLM responses."""
    cache = get_llm_cache()
    success = await cache._backend.clear()
    logger.warning("LLM cache cleared via admin API")
    return {"cleared": success}


# ==========================================================
# CIRCUIT BREAKER
# ==========================================================

@router.get(
    "/circuit-breaker/status",
    summary="Circuit breaker status",
    dependencies=[Depends(_require_api_key)],
)
async def circuit_breaker_status() -> Dict[str, Any]:
    """Return current circuit breaker state and counters."""
    circuit = get_llm_circuit_breaker()
    return circuit.get_status()


@router.post(
    "/circuit-breaker/reset",
    summary="Force-reset circuit breaker to CLOSED",
    dependencies=[Depends(_require_api_key)],
)
async def reset_circuit_breaker() -> Dict[str, Any]:
    """
    Manually reset the circuit breaker to CLOSED state.
    Use when you have confirmed the underlying issue is resolved and
    want to restore traffic without waiting for the recovery timeout.
    """
    circuit = get_llm_circuit_breaker()
    async with circuit._lock:
        old_state = circuit._state.value
        circuit._state = CircuitState.CLOSED
        circuit._failure_count = 0
        circuit._last_failure_time = None

    logger.warning(
        "Circuit breaker manually reset to CLOSED | previous_state=%s", old_state
    )
    return {"reset": True, "previous_state": old_state, "current_state": "closed"}


# ==========================================================
# METRICS SNAPSHOT
# ==========================================================

@router.get(
    "/metrics",
    summary="Full application metrics snapshot",
    dependencies=[Depends(_require_api_key)],
)
async def admin_metrics() -> Dict[str, Any]:
    """Full metrics dump including error breakdown and LLM call stats."""
    metrics = get_metrics()
    return metrics.get_metrics()


# ==========================================================
# CONFIG INTROSPECTION (non-sensitive fields only)
# ==========================================================

@router.get(
    "/config",
    summary="Non-sensitive config values",
    dependencies=[Depends(_require_api_key)],
)
async def admin_config() -> Dict[str, Any]:
    """
    Return non-sensitive configuration for debugging deployment issues.
    API keys and secrets are never exposed.
    """
    s = get_settings()
    return {
        "env": s.ENV,
        "version": s.VERSION,
        "llm_provider": s.LLM_PROVIDER,
        "primary_model": s.PRIMARY_MODEL,
        "fallback_model": s.FALLBACK_MODEL,
        "max_concurrent_llm_calls": s.MAX_CONCURRENT_LLM_CALLS,
        "llm_timeout_seconds": s.LLM_TIMEOUT_SECONDS,
        "rate_limit_enabled": s.RATE_LIMIT_ENABLED,
        "rate_limit_requests": s.RATE_LIMIT_REQUESTS,
        "rate_limit_window_seconds": s.RATE_LIMIT_WINDOW_SECONDS,
        "cache_enabled": s.CACHE_ENABLED,
        "cache_ttl_seconds": s.CACHE_TTL_SECONDS,
        "redis_configured": bool(s.REDIS_URL),
        "circuit_breaker_enabled": s.CIRCUIT_BREAKER_ENABLED,
        "circuit_breaker_failure_threshold": s.CIRCUIT_BREAKER_FAILURE_THRESHOLD,
        "circuit_breaker_recovery_timeout": s.CIRCUIT_BREAKER_RECOVERY_TIMEOUT,
        "batch_max_items": s.BATCH_MAX_ITEMS,
        "batch_max_parallel": s.BATCH_MAX_PARALLEL,
        "stream_max_concurrent": s.STREAM_MAX_CONCURRENT,
        "generation_timeout_seconds": s.GENERATION_TIMEOUT_SECONDS,
        "cleanup_enabled": s.CLEANUP_ENABLED,
        "cleanup_max_age_hours": s.CLEANUP_MAX_AGE_HOURS,
        "intent_correction_enabled": s.INTENT_CORRECTION_ENABLED,
        "metrics_enabled": s.METRICS_ENABLED,
        "tracing_enabled": s.TRACING_ENABLED,
        "log_level": s.LOG_LEVEL,
        "log_format": s.LOG_FORMAT,
        "cors_origins": s.CORS_ORIGINS,
    }
