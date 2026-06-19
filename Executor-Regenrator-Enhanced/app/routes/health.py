from fastapi import APIRouter
from fastapi.responses import JSONResponse
from app.core.config import get_settings
from app.core.health import get_health_checker, HealthStatus

router = APIRouter()
settings = get_settings()

@router.get("", tags=["health"])
async def health_check():
    return {
        "status": "ok",
        "version": settings.VERSION,
        "env": settings.ENV,
    }

@router.get("/live", tags=["health"])
async def liveness_check():
    checker = get_health_checker()
    report = await checker.liveness_check()
    status_code = 200 if report.status == HealthStatus.HEALTHY else 503
    return JSONResponse(status_code=status_code, content=report.to_dict())

@router.get("/ready", tags=["health"])
async def readiness_check():
    checker = get_health_checker()
    report = await checker.readiness_check()
    status_code = 200 if report.status in (HealthStatus.HEALTHY, HealthStatus.DEGRADED) else 503
    return JSONResponse(status_code=status_code, content=report.to_dict())

@router.get("/startup", tags=["health"])
async def startup_check():
    checker = get_health_checker()
    report = await checker.startup_check()
    status_code = 200 if report.status == HealthStatus.HEALTHY else 503
    return JSONResponse(status_code=status_code, content=report.to_dict())

@router.get("/deep", tags=["health"])
async def deep_health_check():
    checker = get_health_checker()
    report = await checker.deep_check()
    return JSONResponse(status_code=200, content=report.to_dict())
