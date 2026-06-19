import time
from threading import Lock

from app.core.cache import cache_size
from app.core.config import get_settings
from app.db.mongo import ping_db
from app.services.embeddings import is_embedding_model_loaded

settings = get_settings()
_START_TIME = time.time()
_runtime_lock = Lock()
_request_count = 0
_error_count = 0


def increment_request_metric() -> None:
    global _request_count
    with _runtime_lock:
        _request_count += 1


def increment_error_metric() -> None:
    global _error_count
    with _runtime_lock:
        _error_count += 1


def get_runtime_metrics() -> dict:
    with _runtime_lock:
        return {
            "requests": _request_count,
            "errors": _error_count,
        }


async def health_check_basic() -> dict:
    return {
        "status": "ok",
        "service": settings.APP_NAME,
        "version": settings.VERSION,
    }


async def health_check_live() -> dict:
    return {
        "status": "alive",
        "uptime": round(time.time() - _START_TIME, 3),
    }


async def health_check_ready() -> dict:
    try:
        await ping_db()
        db_status = "connected"
    except Exception:
        db_status = "disconnected"

    embeddings_status = "loaded" if is_embedding_model_loaded() else "not_loaded"
    status = "ready" if db_status == "connected" and embeddings_status == "loaded" else "not_ready"

    return {
        "status": status,
        "db": db_status,
        "embeddings": embeddings_status,
    }


async def health_check_deep() -> dict:
    ready_status = await health_check_ready()
    ready_status["version"] = settings.VERSION
    ready_status["uptime"] = round(time.time() - _START_TIME, 3)
    ready_status["runtime"] = get_runtime_metrics()
    ready_status["cache_entries"] = cache_size()
    ready_status["environment"] = settings.ENVIRONMENT
    return ready_status
