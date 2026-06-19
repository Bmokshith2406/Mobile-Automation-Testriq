from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import assert_valid_startup_settings, get_settings
from app.core.health import (
    health_check_basic,
    health_check_deep,
    health_check_live,
    health_check_ready,
)
from app.core.logging import logger, setup_logging
from app.core.metrics import Metrics
from app.db.mongo import close_mongo_connection, validate_mongo_connection
from app.middleware.audit import AuditMiddleware
from app.middleware.context import ErrorHandlingMiddleware, RequestContextMiddleware
from app.routes import extract, extract_project

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting application lifespan...")
    try:
        assert_valid_startup_settings(settings)
        await validate_mongo_connection()
    except Exception as err:
        logger.error(f"Application startup failed: {err}")
        if settings.FAIL_FAST_STARTUP:
            raise
    yield
    logger.info("Application shutdown initiated")
    await close_mongo_connection()


def create_app() -> FastAPI:
    setup_logging(settings.LOG_LEVEL)

    app = FastAPI(
        title="Playwright Python Method Extractor (AST-Based)",
        version=settings.VERSION,
        description="Extract byte-perfect Python Playwright methods using AST parsing.",
        lifespan=lifespan,
    )

    allow_credentials = settings.CORS_ALLOWED_ORIGINS != ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ALLOWED_ORIGINS,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(ErrorHandlingMiddleware)
    app.add_middleware(AuditMiddleware)
    app.add_middleware(RequestContextMiddleware)

    app.include_router(extract.router, prefix="/extract", tags=["Extraction"])
    app.include_router(extract_project.router, prefix="/extract-project", tags=["Project Extraction"])

    @app.get("/health", tags=["Health"])
    async def get_health():
        return await health_check_basic()

    @app.get("/health/live", tags=["Health"])
    async def get_health_live():
        return await health_check_live()

    @app.get("/health/ready", tags=["Health"])
    async def get_health_ready():
        return await health_check_ready()

    @app.get("/health/deep", tags=["Health"])
    async def get_health_deep():
        return await health_check_deep()

    from fastapi.responses import Response

    @app.get("/metrics", tags=["Operations"])
    async def metrics_prometheus():
        return Response(
            content=Metrics.render_prometheus_metrics(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    @app.get("/metrics/json", tags=["Operations"])
    async def metrics_json():
        return Metrics.get_metrics_snapshot()

    return app


app = create_app()
