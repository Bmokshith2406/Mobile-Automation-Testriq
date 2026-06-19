# app/routes/metrics.py
"""
Metrics Endpoint

Production-ready metrics:
- Safe subsystem isolation
- Proper Prometheus content-type
- Defensive dict access
- No import-time config execution
- Structured logging
"""

from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.responses import PlainTextResponse, JSONResponse
from fastapi.security import APIKeyHeader
from typing import Dict, Any
import hmac
import logging

from app.core.metrics import get_metrics
from app.core.cache import get_llm_cache
from app.core.circuit_breaker import get_llm_circuit_breaker
from app.core.config import get_settings


def _require_api_key(
    api_key: str = Security(APIKeyHeader(name="X-API-Key", auto_error=False)),
) -> None:
    settings = get_settings()
    if not settings.API_KEY_ENABLED:
        return
    if not api_key or not hmac.compare_digest(api_key, settings.API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

router = APIRouter()
logger = logging.getLogger("api.metrics")


# ==========================================================
# JSON METRICS
# ==========================================================

@router.get("/", summary="Application metrics (JSON)", dependencies=[Depends(_require_api_key)])
async def get_application_metrics() -> Dict[str, Any]:

    settings = get_settings()

    if not settings.METRICS_ENABLED:
        logger.warning("Metrics requested but disabled")
        raise HTTPException(status_code=503, detail="Metrics disabled")

    result: Dict[str, Any] = {}

    # Core metrics
    try:
        metrics = get_metrics()
        result.update(metrics.get_metrics())
    except Exception as e:
        logger.exception("Core metrics collection failed")
        result["core_metrics_error"] = str(e)

    # Cache metrics
    try:
        cache = get_llm_cache()
        result["cache"] = cache.get_stats()
    except Exception as e:
        logger.exception("Cache metrics failed")
        result["cache_error"] = str(e)

    # Circuit breaker metrics
    try:
        circuit = get_llm_circuit_breaker()
        result["circuit_breaker"] = circuit.get_status()
    except Exception as e:
        logger.exception("Circuit breaker metrics failed")
        result["circuit_breaker_error"] = str(e)

    return result


# ==========================================================
# PROMETHEUS FORMAT
# ==========================================================

@router.get(
    "/prometheus",
    summary="Prometheus metrics",
    response_class=PlainTextResponse,
    dependencies=[Depends(_require_api_key)],
)
async def get_prometheus_metrics():

    settings = get_settings()

    if not settings.METRICS_ENABLED:
        logger.warning("Prometheus scrape attempted but metrics disabled")
        return PlainTextResponse(
            "# Metrics disabled\n",
            status_code=503,
            media_type="text/plain; version=0.0.4",
        )

    try:
        metrics = get_metrics()
        data = metrics.get_metrics()
    except Exception as e:
        logger.exception("Prometheus metrics generation failed")
        return PlainTextResponse(
            "# Metrics collection failed\n",
            status_code=500,
            media_type="text/plain; version=0.0.4",
        )

    # Safe nested access
    requests = data.get("requests", {})
    llm = data.get("llm", {})
    generator = data.get("generator", {})

    lines = [
        "# HELP app_uptime_seconds Application uptime in seconds",
        "# TYPE app_uptime_seconds gauge",
        f'app_uptime_seconds {data.get("uptime_seconds", 0)}',
        "",
        "# HELP app_requests_total Total number of requests",
        "# TYPE app_requests_total counter",
        f'app_requests_total {requests.get("total", 0)}',
        f'app_requests_success_total {requests.get("success", 0)}',
        f'app_requests_failed_total {requests.get("failed", 0)}',
        "",
        "# HELP app_requests_in_progress Current requests being processed",
        "# TYPE app_requests_in_progress gauge",
        f'app_requests_in_progress {requests.get("in_progress", 0)}',
        "",
        "# HELP app_llm_calls_total Total LLM API calls",
        "# TYPE app_llm_calls_total counter",
        f'app_llm_calls_total {llm.get("calls_total", 0)}',
        f'app_llm_calls_success_total {llm.get("calls_success", 0)}',
        f'app_llm_calls_failed_total {llm.get("calls_failed", 0)}',
        f'app_llm_calls_cached_total {llm.get("calls_cached", 0)}',
        "",
        "# HELP app_llm_tokens_total Total LLM tokens used",
        "# TYPE app_llm_tokens_total counter",
        f'app_llm_tokens_input_total {llm.get("tokens_input", 0)}',
        f'app_llm_tokens_output_total {llm.get("tokens_output", 0)}',
        "",
        "# HELP app_scripts_generated_total Total scripts generated",
        "# TYPE app_scripts_generated_total counter",
        f'app_scripts_generated_total {generator.get("scripts_generated", 0)}',
        "",
    ]

    return PlainTextResponse(
        "\n".join(lines),
        media_type="text/plain; version=0.0.4",
    )
