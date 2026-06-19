from fastapi import APIRouter
from fastapi.responses import JSONResponse, PlainTextResponse
from app.core.config import get_settings
from app.core.metrics import get_metrics

router = APIRouter()

@router.get("", tags=["observability"])
async def metrics_endpoint():
    if not get_settings().ENABLE_METRICS:
        return JSONResponse(
            status_code=404,
            content={"detail": "Metrics not enabled"},
        )

    metrics = get_metrics()
    return PlainTextResponse(
        content=metrics.export_prometheus(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
