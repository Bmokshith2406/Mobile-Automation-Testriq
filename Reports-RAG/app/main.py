from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app.core.security import verify_admin_api_key

from app.core.config import assert_valid_startup_settings, settings
from app.core.errors import ProductionError
from app.core.health import (
    health_check_basic,
    health_check_deep,
    health_check_live,
    health_check_ready,
)
from app.core.logging import get_logger
from app.core.metrics import Metrics
from app.db.mongo import connect_to_mongo, disconnect_from_mongo, ensure_indexes
from app.middleware.context import ErrorHandlingMiddleware, RequestContextMiddleware
from app.routes import report

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("Starting Reports RAG")
    try:
        assert_valid_startup_settings(settings)

        if settings.mongo_enabled:
            await connect_to_mongo()
            await ensure_indexes()
            logger.info("Application initialized successfully")
        else:
            logger.warning("MongoDB is disabled; report endpoints will not be available")
    except Exception as exc:
        logger.exception("Application startup failed", extra={"error": str(exc)})
        if settings.FAIL_FAST_STARTUP:
            raise

    try:
        yield
    finally:
        await disconnect_from_mongo()
        logger.info("Application shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        description="HTML report storage and retrieval system",
        version=settings.APP_VERSION,
        lifespan=lifespan,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url=None,
    )

    app.add_middleware(ErrorHandlingMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-API-Key",
            "X-Admin-API-Key",
            "X-Request-ID",
            "X-Correlation-ID",
        ],
    )

    app.include_router(report.router, prefix="/v1")
    app.include_router(report.admin_router, prefix="/v1")

    @app.exception_handler(ProductionError)
    async def production_error_handler(_: Request, exc: ProductionError):
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.detail,
            headers=exc.headers,
        )

    @app.get("/health", tags=["Health"])
    async def get_health():
        return await health_check_basic()

    @app.get("/health/live", tags=["Health"])
    async def get_health_live():
        return await health_check_live()

    @app.get("/health/ready", tags=["Health"])
    async def get_health_ready():
        payload = await health_check_ready()
        status_code = 200 if payload["status"] == "ready" else 503
        return JSONResponse(status_code=status_code, content=payload)

    @app.get("/health/deep", tags=["Health"])
    async def get_health_deep():
        payload = await health_check_deep()
        status_code = 200 if payload["status"] == "ready" else 503
        return JSONResponse(status_code=status_code, content=payload, headers={"Cache-Control": "no-store"})

    @app.get("/metrics", tags=["Operations"])
    async def metrics_prometheus(current_user: dict = Depends(verify_admin_api_key)):
        return Response(
            content=Metrics.render_prometheus_metrics(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    @app.get("/metrics/json", tags=["Operations"])
    async def metrics_json(current_user: dict = Depends(verify_admin_api_key)):
        return Metrics.get_metrics_snapshot()

    @app.get("/")
    async def root():
        return {
            "service": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "status": "running",
            "environment": settings.ENV,
            "docs": "/docs" if not settings.is_production else "disabled",
            "endpoints": {
                "health": "/health",
                "upload": "POST /v1/api/reports/upload",
                "download": "GET /v1/api/reports/download/{report_id}",
                "admin_list": "GET /v1/api/reports",
                "admin_delete": "DELETE /v1/api/reports/{report_id}",
                "admin_delete_all": "POST /v1/api/reports/delete-all?confirm=true",
            },
        }

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.ENV == "development",
        workers=1 if settings.ENV == "development" else 2,
    )
