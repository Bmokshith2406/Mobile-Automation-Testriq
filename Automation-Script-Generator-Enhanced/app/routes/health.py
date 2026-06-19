# app/routes/health.py
"""
Health Check Endpoints

Production-ready health system:
- Liveness
- Readiness
- Deep diagnostics
- Timeout protection
- Proper status codes
- Structured logging
"""

from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from typing import Dict, Any
import asyncio
import hmac
import logging

from app.core.config import get_settings
from app.core.llm_executor import get_llm_executor
from app.core.circuit_breaker import get_llm_circuit_breaker
from app.core.cache import get_llm_cache


def _require_api_key(
    api_key: str = Security(APIKeyHeader(name="X-API-Key", auto_error=False)),
) -> None:
    """Dependency that enforces the API key for sensitive health endpoints."""
    settings = get_settings()
    if not settings.API_KEY_ENABLED:
        return
    if not api_key or not hmac.compare_digest(api_key, settings.API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

router = APIRouter()
logger = logging.getLogger("api.health")


# ==========================================================
# LIVENESS
# ==========================================================

@router.get("/", summary="Liveness probe")
async def health_check() -> Dict[str, Any]:
    """
    Basic liveness check.

    Used by load balancers for quick health verification.
    Should NEVER perform external calls.
    """
    settings = get_settings()

    return {
        "status": "ok",
        "version": settings.VERSION,
        "env": settings.ENV,
    }


# ==========================================================
# READINESS
# ==========================================================

@router.get("/ready", summary="Readiness probe")
async def readiness_check():
    """
    Readiness check.

    Verifies system is ready to serve traffic.
    Does NOT perform heavy checks.
    """

    settings = get_settings()
    circuit = get_llm_circuit_breaker()

    ready = circuit.is_closed or not settings.CIRCUIT_BREAKER_ENABLED

    status = "ready" if ready else "not_ready"

    payload = {
        "status": status,
        "version": settings.VERSION,
        "circuit_breaker": circuit.state.value,
    }

    if not ready:
        logger.warning("Readiness failed - circuit breaker open")
        return JSONResponse(status_code=503, content=payload)

    return payload


# ==========================================================
# DEEP HEALTH CHECK
# ==========================================================

@router.get("/deep", summary="Deep health diagnostics (requires API key)")
async def deep_health_check(_: None = Depends(_require_api_key)):
    """
    Deep health check.

    Performs:
    - LLM provider connectivity check (with timeout)
    - Circuit breaker status
    - Cache stats

    Should NOT be used by load balancers.
    """

    settings = get_settings()

    result: Dict[str, Any] = {
        "status": "healthy",
        "version": settings.VERSION,
        "env": settings.ENV,
        "checks": {},
    }

    issues = []

    # ------------------------------------------------------
    # LLM CHECK (with timeout protection)
    # ------------------------------------------------------
    try:
        executor = get_llm_executor()

        llm_health = await asyncio.wait_for(
            executor.health_check(),
            timeout=5.0,
        )

        result["checks"]["llm"] = llm_health

        primary = llm_health.get("primary_provider")

        if not primary:
            issues.append("No primary LLM provider configured")
        elif not primary.get("healthy", False):
            issues.append("Primary LLM provider unhealthy")

    except asyncio.TimeoutError:
        logger.error("LLM health check timeout")
        result["checks"]["llm"] = {"error": "timeout"}
        issues.append("LLM health check timeout")

    except Exception as e:
        logger.exception("LLM health check failed")
        result["checks"]["llm"] = {"error": str(e)}
        issues.append("LLM health check failed")

    # ------------------------------------------------------
    # CIRCUIT BREAKER CHECK
    # ------------------------------------------------------
    try:
        circuit = get_llm_circuit_breaker()
        result["checks"]["circuit_breaker"] = circuit.get_status()

        if circuit.is_open:
            issues.append("Circuit breaker is OPEN")

    except Exception as e:
        logger.exception("Circuit breaker check failed")
        result["checks"]["circuit_breaker"] = {"error": str(e)}
        issues.append("Circuit breaker check failed")

    # ------------------------------------------------------
    # CACHE CHECK
    # ------------------------------------------------------
    try:
        cache = get_llm_cache()
        result["checks"]["cache"] = cache.get_stats()

    except Exception as e:
        logger.exception("Cache health check failed")
        result["checks"]["cache"] = {"error": str(e)}
        issues.append("Cache health check failed")

    # ------------------------------------------------------
    # FINAL STATUS
    # ------------------------------------------------------
    if issues:
        result["status"] = "degraded"
        result["issues"] = issues

        logger.warning(
            "Deep health degraded",
            extra={"issues": issues},
        )

        return JSONResponse(status_code=503, content=result)

    logger.info("Deep health check successful")

    return result

