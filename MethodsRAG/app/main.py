from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from app.core.security import verify_admin_api_key

from app.core.config import get_settings, assert_valid_startup_settings
from app.core.error_handler import register_exception_handlers
from app.core.health import health_check_basic, health_check_live, health_check_ready, health_check_deep
from app.core.logging import logger
from app.core.metrics import Metrics
from app.core.gemini_client import get_gemini_client

from app.db.mongo import ping_db, close_db
from app.db.indexes import create_indexes
from app.services.embeddings import load_embedding_model, unload_embedding_model

from app.middleware.context import RequestContextMiddleware

from app.routes import upload, search, admin, update

settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting application lifespan...")

    try:
        assert_valid_startup_settings(settings)
    except Exception as e:
        logger.critical(f"Configuration validation failed: {e}")
        if settings.FAIL_FAST_STARTUP:
            raise

    # Validate Gemini API key
    try:
        model = await get_gemini_client()
        if model is None:
            raise RuntimeError("Gemini API key validation failed - model is None")
        logger.info("Gemini API key validated successfully")
    except Exception as e:
        logger.critical(f"Gemini API validation failed: {e}")
        if settings.FAIL_FAST_STARTUP:
            raise

    # MongoDB connection
    try:
        await ping_db()
        logger.info("MongoDB connected successfully")
    except Exception as e:
        logger.critical(f"MongoDB connection failed: {e}", exc_info=True)
        if settings.FAIL_FAST_STARTUP:
            raise
    
    # Create database indexes
    try:
        await create_indexes()
        logger.info("Database indexes created")
    except Exception as e:
        logger.warning(f"Error creating indexes: {e}")

    # Load embeddings
    try:
        await load_embedding_model()
        logger.info("Embedding model loaded successfully")
    except Exception as e:
        logger.critical(f"Embedding model load failed: {e}", exc_info=True)
        if settings.FAIL_FAST_STARTUP:
            raise

    yield

    logger.info("Shutting down application...")

    try:
        await close_db()
        logger.info("MongoDB connection closed")
    except Exception as e:
        logger.warning(f"Database shutdown encountered an issue: {e}")

    try:
        await unload_embedding_model()
        logger.info("Embedding model unloaded")
    except Exception as e:
        logger.warning(f"Embedding model unload encountered an issue: {e}")

    logger.info("Lifespan shutdown complete")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key", "X-Admin-API-Key", "X-Request-ID"],
    max_age=3600,
)

# Standard Middlewares
app.add_middleware(RequestContextMiddleware)
register_exception_handlers(app)

# Routers
app.include_router(upload.router, prefix="/api", tags=["Upload"])
app.include_router(search.router, prefix="/api", tags=["Search"])
app.include_router(update.router, prefix="/api", tags=["Update"])
app.include_router(admin.router, prefix="/api", tags=["Admin"])

# Health
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

# Metrics
@app.get("/metrics", tags=["Operations"])
async def metrics_prometheus(current_user: dict = Depends(verify_admin_api_key)):
    return Response(
        content=Metrics.render_prometheus_metrics(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )

@app.get("/metrics/json", tags=["Operations"])
async def metrics_json(current_user: dict = Depends(verify_admin_api_key)):
    return Metrics.get_metrics_snapshot()

@app.get("/", tags=["Health"])
async def root():
    return {
        "status": "running",
        "service": settings.APP_NAME,
        "version": settings.VERSION,
        "docs": "/docs",
    }
