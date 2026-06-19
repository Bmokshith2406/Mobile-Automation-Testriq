from pathlib import Path

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.openapi.utils import get_openapi
from contextlib import asynccontextmanager

from app.core.cache_layer import cache_manager
from app.core.config import assert_valid_startup_settings, get_settings
from app.core.logging import logger
from app.core.errors import ProductionError, internal_error
from app.core.health import (
    health_check_basic,
    health_check_live,
    health_check_ready,
    health_check_deep,
    increment_error_metric,
)
from app.core.metrics import Metrics
from app.core.security import verify_admin_api_key
from app.middleware.context import RequestContextMiddleware, ErrorHandlingMiddleware
from app.db.mongo import ping_db, close_db, create_indexes
from app.llm.client import LLMClientManager
from app.services.embeddings import load_embedding_model, unload_embedding_model
from app.services.ingestion_jobs import ingestion_job_manager
from app.routes import admin, scripts, search, update, upload, ingest


# ------------------------------------------------------------------
# Settings
# ------------------------------------------------------------------

settings = get_settings()
# Removed frontend dir references

# ------------------------------------------------------------------
# Lifespan manager
# ------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting application lifespan...")
    try:
        assert_valid_startup_settings(settings)
        await cache_manager.init()
        await ping_db()
        await load_embedding_model()
        await create_indexes()
        await ingestion_job_manager.start()

        llm_manager = LLMClientManager.get_instance()
        if llm_manager.available:
            logger.info(
                "LLM provider initialized",
                extra={
                    "provider": llm_manager.provider_name,
                    "model": llm_manager.model_name,
                },
            )
        else:
            logger.warning("No LLM provider available; LLM-backed features will use fallbacks.")
    except Exception as err:
        logger.error("Application startup failed", extra={"error": str(err)}, exc_info=True)
        if settings.FAIL_FAST_STARTUP:
            raise
        logger.warning("Continuing startup in degraded mode because FAIL_FAST_STARTUP=false")

    try:
        yield
    finally:
        try:
            await ingestion_job_manager.stop()
        except Exception as err:
            logger.warning(f"Ingestion worker shutdown encountered an issue: {err}")

        try:
            await cache_manager.close()
        except Exception as err:
            logger.warning(f"Cache shutdown encountered an issue: {err}")

        try:
            await close_db()
        except Exception as err:
            logger.warning(f"Database shutdown encountered an issue: {err}")

        try:
            await unload_embedding_model()
        except Exception as err:
            logger.warning(f"Embedding model unload encountered an issue: {err}")

        try:
            existing_llm_manager = LLMClientManager._instance
            if existing_llm_manager is not None:
                existing_llm_manager.close(wait=False)
        except Exception as err:
            logger.warning(f"LLM manager shutdown encountered an issue: {err}")

        logger.info("Lifespan shutdown complete")


# ------------------------------------------------------------------
# App initialization
# ------------------------------------------------------------------

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
)

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=settings.APP_NAME,
        version=settings.VERSION,
        description=(
            "Secure API with JWT bearer authentication, scoped RBAC, "
            "background ingestion, distributed cache support, and operability endpoints"
        ),
        routes=app.routes,
    )

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi


# Removed frontend file helper

# ------------------------------------------------------------------
# Middleware - Restrict origins to configured clients
# ------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Accept",
        "Origin",
        "X-API-Key",
        "X-Admin-API-Key",
        "X-Request-ID",
    ],
)
app.add_middleware(ErrorHandlingMiddleware)
app.add_middleware(RequestContextMiddleware)


# ------------------------------------------------------------------
# Routers - Added new scripts fetch router
# ------------------------------------------------------------------

app.include_router(upload.router, prefix="/api", tags=["Upload"])
app.include_router(search.router, prefix="/api", tags=["Search"])
app.include_router(scripts.router, prefix="/api", tags=["Scripts"])
app.include_router(update.router, prefix="/api", tags=["Update"])
app.include_router(admin.router, prefix="/api", tags=["Admin"])
app.include_router(ingest.router, prefix="/api", tags=["Ingest"])


# Removed frontend SPA routes


# ------------------------------------------------------------------
# Structured exception handlers
# ------------------------------------------------------------------

@app.exception_handler(ProductionError)
async def production_error_handler(request: Request, exc: ProductionError):
    """Handle all production errors with structured response."""
    increment_error_metric()
    response_data = {
        "error": {
            "code": exc.error_code.value,
            "message": exc.error_message,
            "request_id": exc.request_id,
            "timestamp": exc.timestamp,
            "details": exc.error_details,
            "retry_after": exc.retry_after,
            "correlation_id": exc.correlation_id,
        }
    }
    
    headers = {
        "X-Request-ID": exc.request_id,
        "X-Correlation-ID": exc.correlation_id,
    }
    if exc.retry_after:
        headers["Retry-After"] = str(exc.retry_after)
    
    return JSONResponse(
        status_code=exc.status_code,
        content=response_data,
        headers=headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Convert Pydantic validation errors to structured format."""
    from app.core.errors import validation_error
    increment_error_metric()
    
    errors = []
    for error in exc.errors():
        errors.append({
            "field": ".".join(str(x) for x in error["loc"]),
            "message": error["msg"],
            "type": error["type"],
        })
    
    prod_error = validation_error(
        "Request validation failed",
        details={"validation_errors": errors}
    )
    
    response_data = {
        "error": {
            "code": prod_error.error_code.value,
            "message": prod_error.error_message,
            "request_id": prod_error.request_id,
            "timestamp": prod_error.timestamp,
            "details": prod_error.error_details,
        }
    }
    
    return JSONResponse(
        status_code=422,
        content=response_data,
        headers={"X-Request-ID": prod_error.request_id},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Catch any unhandled exceptions."""
    request_id = getattr(request.state, "request_id", "unknown")
    increment_error_metric()
    
    logger.error(
        f"Unhandled exception: {exc}",
        exc_info=True,
        extra={"request_id": request_id}
    )
    
    error = internal_error(request_id=request_id)
    response_data = {
        "error": {
            "code": error.error_code.value,
            "message": error.error_message,
            "request_id": error.request_id,
            "timestamp": error.timestamp,
        }
    }
    
    return JSONResponse(
        status_code=500,
        content=response_data,
        headers={"X-Request-ID": request_id},
    )


# ------------------------------------------------------------------
# Health check endpoints for production monitoring
# ------------------------------------------------------------------

@app.get("/health", tags=["Health"])
async def health_basic():
    """Basic health check - process is alive."""
    return await health_check_basic()


@app.get("/health/live", tags=["Health"])
async def health_live():
    """Kubernetes liveness probe."""
    return await health_check_live()


@app.get("/health/ready", tags=["Health"])
async def health_ready():
    """Kubernetes readiness probe."""
    return await health_check_ready()


@app.get("/health/deep", tags=["Health"])
async def health_deep():
    """Detailed health diagnostics."""
    return await health_check_deep()


@app.get("/metrics", tags=["Operations"])
async def metrics_prometheus(
    current_user: dict = Depends(verify_admin_api_key),
):
    """Prometheus-compatible metrics output."""
    return Response(
        content=Metrics.render_prometheus_metrics(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.get("/metrics/json", tags=["Operations"])
async def metrics_json(
    current_user: dict = Depends(verify_admin_api_key),
):
    """Structured metrics snapshot for debugging and dashboards."""
    return Metrics.get_metrics_snapshot()


# ------------------------------------------------------------------
# Health endpoint
# ------------------------------------------------------------------

@app.get("/")
async def root():
    return {
        "status": "running",
        "service": settings.APP_NAME,
        "version": settings.VERSION,
        "docs_url": "/docs",
        "port": settings.API_PORT
    }
