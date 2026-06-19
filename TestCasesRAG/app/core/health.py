"""
Health check endpoints for production monitoring.
Supports Kubernetes liveness/readiness probes and detailed diagnostics.
"""

from datetime import datetime, timezone
from typing import Dict, Any
import time
from threading import Lock

from app.db.mongo import get_db, is_mongodb_healthy
from app.core.logging import logger
from app.core.config import get_settings, validate_startup_settings

settings = get_settings()

# Track health metrics
_health_metrics = {
    "startup_time": time.time(),
    "requests_total": 0,
    "errors_total": 0,
}

_metrics_lock = Lock()


def _utc_timestamp() -> str:
    """Generate ISO UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


async def check_database_health() -> Dict[str, Any]:
    """Check MongoDB connectivity and performance."""
    start_time = time.perf_counter()

    try:
        db = get_db()

        # Ping database
        await db.client.admin.command("ping")

        latency_ms = (time.perf_counter() - start_time) * 1000

        return {
            "status": "healthy",
            "latency_ms": round(latency_ms, 2),
            "timestamp": _utc_timestamp(),
        }

    except Exception as e:
        logger.error(
            "database_health_check_failed",
            extra={"error": str(e)},
        )

        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": _utc_timestamp(),
        }


def check_embedding_model_health() -> Dict[str, Any]:
    """Check if embedding model is loaded."""
    try:
        # Import here to avoid circular imports
        from app.services.embeddings import _embedding_model, get_embedding_backend_info

        backend = get_embedding_backend_info()

        if _embedding_model is not None:
            return {
                "status": "healthy",
                "preset": backend.get("preset"),
                "model_name": backend.get("model_name"),
                "dimensions": backend.get("dimensions"),
                "timestamp": _utc_timestamp(),
            }

        return {
            "status": "loading",
            "preset": backend.get("preset"),
            "model_name": backend.get("model_name"),
            "dimensions": backend.get("dimensions"),
            "timestamp": _utc_timestamp(),
        }

    except Exception as e:
        logger.error(
            "embedding_model_health_check_failed",
            extra={"error": str(e)},
        )

        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": _utc_timestamp(),
        }


def check_llm_health() -> Dict[str, Any]:
    """Check the configured LLM backend and runtime availability."""
    try:
        from app.llm.client import LLMClientManager

        llm_manager = LLMClientManager.get_instance()
        health = llm_manager.health()
        health["status"] = "healthy" if health.get("available") else "disabled"
        health["timestamp"] = _utc_timestamp()
        return health
    except Exception as e:
        logger.error(
            "llm_health_check_failed",
            extra={"error": str(e)},
        )
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": _utc_timestamp(),
        }


async def check_cache_health() -> Dict[str, Any]:
    """Check cache backend connectivity and status."""
    try:
        from app.core.cache import get_cache_health

        stats = await get_cache_health()
        return {
            "status": stats.get("status", "healthy"),
            "details": stats,
            "timestamp": _utc_timestamp(),
        }
    except Exception as e:
        logger.error(
            "cache_health_check_failed",
            extra={"error": str(e)},
        )
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": _utc_timestamp(),
        }


def check_configuration_health() -> Dict[str, Any]:
    """Validate runtime configuration."""
    try:
        errors = validate_startup_settings(settings)
        return {
            "status": "healthy" if not errors else "unhealthy",
            "errors": errors,
            "timestamp": _utc_timestamp(),
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": _utc_timestamp(),
        }


def check_ingestion_health() -> Dict[str, Any]:
    """Check background ingestion workers and queue state."""
    try:
        from app.services.ingestion_jobs import ingestion_job_manager

        stats = ingestion_job_manager.get_runtime_stats()
        return {
            "status": "healthy" if stats.get("started") else "starting",
            "details": stats,
            "timestamp": _utc_timestamp(),
        }
    except Exception as e:
        logger.error(
            "ingestion_health_check_failed",
            extra={"error": str(e)},
        )
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": _utc_timestamp(),
        }


async def health_check_basic() -> Dict[str, Any]:
    """Basic health check (just checks process is alive)."""
    return {
        "status": "ok",
        "timestamp": _utc_timestamp(),
    }


async def health_check_live() -> Dict[str, Any]:
    """Kubernetes liveness probe - checks if process should be restarted."""
    return {
        "status": "alive",
        "uptime_seconds": time.time() - _health_metrics["startup_time"],
        "timestamp": _utc_timestamp(),
    }


async def health_check_ready() -> Dict[str, Any]:
    """Kubernetes readiness probe - checks if ready to serve traffic."""
    db_health = await check_database_health()
    embedding_health = check_embedding_model_health()
    llm_health = check_llm_health()
    cache_health = await check_cache_health()
    config_health = check_configuration_health()
    ingestion_health = check_ingestion_health()

    all_ready = (
        db_health.get("status") == "healthy"
        and embedding_health.get("status") in ("healthy", "loading")
        and llm_health.get("status") in ("healthy", "disabled")
        and cache_health.get("status") in ("healthy", "degraded")
        and config_health.get("status") == "healthy"
        and ingestion_health.get("status") in ("healthy", "starting")
    )

    if all_ready:
        return {
            "status": "ready",
            "checks": {
                "database": db_health,
                "embedding_model": embedding_health,
                "llm": llm_health,
                "cache": cache_health,
                "configuration": config_health,
                "ingestion": ingestion_health,
            },
            "timestamp": _utc_timestamp(),
        }

    return {
        "status": "not_ready",
        "checks": {
            "database": db_health,
            "embedding_model": embedding_health,
            "llm": llm_health,
            "cache": cache_health,
            "configuration": config_health,
            "ingestion": ingestion_health,
        },
        "timestamp": _utc_timestamp(),
    }


async def health_check_deep() -> Dict[str, Any]:
    """Deep health check with comprehensive diagnostics."""
    db_health = await check_database_health()
    embedding_health = check_embedding_model_health()
    llm_health = check_llm_health()
    cache_health = await check_cache_health()
    config_health = check_configuration_health()
    ingestion_health = check_ingestion_health()

    requests_total = _health_metrics["requests_total"]
    errors_total = _health_metrics["errors_total"]

    return {
        "status": "healthy",
        "timestamp": _utc_timestamp(),
        "uptime_seconds": int(time.time() - _health_metrics["startup_time"]),
        "components": {
            "database": db_health,
            "embedding_model": embedding_health,
            "llm": llm_health,
            "cache": cache_health,
            "configuration": config_health,
            "ingestion": ingestion_health,
        },
        "metrics": {
            "requests_total": requests_total,
            "errors_total": errors_total,
            "error_rate": errors_total / max(1, requests_total),
        },
    }


def increment_request_metric():
    """Track successful request."""
    try:
        with _metrics_lock:
            _health_metrics["requests_total"] += 1
    except Exception:
        pass


def increment_error_metric():
    """Track failed request."""
    try:
        with _metrics_lock:
            _health_metrics["errors_total"] += 1
    except Exception:
        pass
