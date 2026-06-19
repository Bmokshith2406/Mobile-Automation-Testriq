import time

from app.core.config import settings
from app.core.metrics import Metrics
from app.db.mongo import ping_db

_START_TIME = time.time()


def _uptime_seconds() -> float:
    return round(time.time() - _START_TIME, 3)


async def health_check_basic() -> dict:
    return {
        "status": "ok",
        "service": settings.APP_NAME,
        "version": settings.VERSION,
    }


async def health_check_live() -> dict:
    return {
        "status": "alive",
        "uptime_seconds": _uptime_seconds(),
    }


async def health_check_ready() -> dict:
    if not settings.mongo_enabled:
        return {"status": "ready", "db": "disabled"}

    if await ping_db():
        return {"status": "ready", "db": "connected"}

    return {"status": "not_ready", "db": "disconnected"}


async def health_check_deep() -> dict:
    ready_status = await health_check_ready()
    ready_status["version"] = settings.VERSION
    ready_status["uptime_seconds"] = _uptime_seconds()
    ready_status["metrics"] = Metrics.get_metrics_snapshot()
    return ready_status
