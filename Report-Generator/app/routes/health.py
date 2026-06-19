import time
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.services.ai import NoOpAIProvider

router = APIRouter()
settings = get_settings()

START_TIME = time.time()


# ------------------------------------------------------------------------------
# Basic Liveness Probe (Is the process alive?)
# ------------------------------------------------------------------------------
@router.get("/health/live", tags=["Health"])
async def liveness_probe():
    return {
        "status": "alive",
        "service": settings.SERVICE_NAME,
        "timestamp": int(time.time()),
    }


# ------------------------------------------------------------------------------
# Readiness Probe (Is the service ready to accept traffic?)
# ------------------------------------------------------------------------------
@router.get("/health/ready", tags=["Health"])
async def readiness_probe(request: Request):
    import tempfile
    import os
    
    dependencies = {
        "llm_provider": settings.LLM_PROVIDER,
        "fs_writable": "error",
        "ai_service": "unknown",
    }
    
    try:
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"health check")
            tmp_name = f.name
        os.unlink(tmp_name)
        dependencies["fs_writable"] = "ok"
    except Exception:
        dependencies["fs_writable"] = "error"

    ai_service = getattr(request.app.state, "ai_service", None)
    dependencies["ai_service"] = "degraded" if isinstance(ai_service, NoOpAIProvider) else "ok"

    all_ok = dependencies["fs_writable"] == "ok"

    payload = {
        "status": "ready" if all_ok else "degraded",
        "service": settings.SERVICE_NAME,
        "version": settings.SERVICE_VERSION,
        "environment": settings.ENVIRONMENT,
        "dependencies": dependencies,
        "timestamp": int(time.time()),
    }

    status_code = status.HTTP_200_OK if all_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=status_code, content=payload)


# ------------------------------------------------------------------------------
# Full Health (Human-friendly)
# ------------------------------------------------------------------------------
@router.get("/health", tags=["Health"])
async def health_check():
    uptime_seconds = int(time.time() - START_TIME)

    return {
        "status": "healthy",
        "service": settings.SERVICE_NAME,
        "version": settings.SERVICE_VERSION,
        "environment": settings.ENVIRONMENT,
        "uptime_seconds": uptime_seconds,
        "timestamp": int(time.time()),
    }
