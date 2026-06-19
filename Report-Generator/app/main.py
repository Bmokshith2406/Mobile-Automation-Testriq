import hmac
import sentry_sdk
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, ORJSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.security import APIKeyHeader
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.gzip import GZipMiddleware

from app.core.config import get_settings
from app.core.logger import setup_logging, get_logger
from app.core.exceptions import api_exception_handler, general_exception_handler
from app.core.errors import APIException, ErrorCode, ErrorCategory, ErrorSeverity
from app.middleware.logging import RequestLoggingMiddleware
from app.middleware.rate_limit import rate_limiter
from app.routes import health, report
from app.services.ai import NoOpAIProvider, build_ai_service


settings = get_settings()

setup_logging(
    log_level=settings.LOG_LEVEL,
    service_name=settings.SERVICE_NAME,
    environment=settings.ENVIRONMENT,
)

logger = get_logger("bootstrap")


# ------------------------------------------------------------------------------
# API Key Security
# ------------------------------------------------------------------------------
api_key_header = APIKeyHeader(
    name=settings.API_KEY_HEADER,
    auto_error=False,
)


async def verify_api_key(api_key: str = Security(api_key_header)):

    if not settings.API_KEY_ENABLED:
        return

    if not api_key:
        raise APIException(
            error_code=ErrorCode.UNAUTHORIZED,
            message="API key missing",
            status_code=401,
            category=ErrorCategory.AUTHENTICATION,
            severity=ErrorSeverity.WARNING,
        )

    expected_key = settings.API_KEY.get_secret_value() if settings.API_KEY else ""

    if not hmac.compare_digest(api_key, expected_key):
        raise APIException(
            error_code=ErrorCode.UNAUTHORIZED,
            message="Invalid API key",
            status_code=401,
            category=ErrorCategory.AUTHENTICATION,
            severity=ErrorSeverity.WARNING,
        )


# ------------------------------------------------------------------------------
# Observability: Sentry
# ------------------------------------------------------------------------------
def initialize_sentry():

    if not settings.SENTRY_ENABLED:
        logger.info("Sentry disabled")
        return

    if settings.DEBUG:
        logger.info("Sentry skipped in DEBUG mode")
        return

    if not settings.SENTRY_DSN:
        logger.warning("Sentry DSN missing")
        return

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN.get_secret_value(),
        environment=settings.ENVIRONMENT,
        traces_sample_rate=settings.TRACES_SAMPLE_RATE,
        profiles_sample_rate=settings.PROFILES_SAMPLE_RATE,
        send_default_pii=False,
    )

    logger.info("Sentry initialized")


# ------------------------------------------------------------------------------
# Lifespan
# ------------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):

    try:
        validate_configuration()
        initialize_sentry()
        await rate_limiter.initialize()

        try:
            app.state.ai_service = build_ai_service()
        except Exception as exc:
            logger.error(
                "AI provider initialization failed; falling back to no-op provider",
                extra={"error": str(exc), "provider": settings.LLM_PROVIDER},
            )
            app.state.ai_service = NoOpAIProvider()

        logger.info("======================================")
        logger.info("Service starting")
        logger.info(f"Service: {settings.SERVICE_NAME}")
        logger.info(f"Version: {settings.SERVICE_VERSION}")
        logger.info(f"Environment: {settings.ENVIRONMENT}")
        logger.info(f"LLM Provider: {settings.LLM_PROVIDER}")
        logger.info("======================================")

        yield

    finally:

        logger.info("Service shutting down")

        if settings.SENTRY_ENABLED and not settings.DEBUG:
            sentry_sdk.flush(timeout=5)

        await rate_limiter.shutdown()

        ai_service = getattr(app.state, "ai_service", None)
        if ai_service is not None:
            await ai_service.close()

        logger.info("Shutdown complete")


# ------------------------------------------------------------------------------
# Configuration Validation
# ------------------------------------------------------------------------------
def validate_configuration():

    if not settings.SERVICE_NAME:
        raise RuntimeError("SERVICE_NAME not configured")

    if settings.API_KEY_ENABLED and not (settings.API_KEY and settings.API_KEY.get_secret_value().strip()):
        raise RuntimeError("API_KEY_ENABLED but API_KEY not configured")

    if settings.CORS_ORIGINS == ["*"] and settings.IS_PRODUCTION:
        logger.warning("CORS is open in production")

    if settings.RATE_LIMIT_BACKEND == "redis" and not settings.REDIS_ENABLED:
        logger.warning("RATE_LIMIT_BACKEND is redis but REDIS_URL is empty; memory fallback will be used")


# ------------------------------------------------------------------------------
# App Factory
# ------------------------------------------------------------------------------
def create_app() -> FastAPI:

    openapi_tags = [
        {"name": "Health", "description": "Service health endpoints"},
        {"name": "Reports", "description": "Automation report APIs"},
    ]

    app = FastAPI(
        title=settings.SERVICE_NAME,
        version=settings.SERVICE_VERSION,
        description="AI powered automation report generation service",
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
        openapi_url="/openapi.json" if settings.DEBUG else None,
        openapi_tags=openapi_tags,
        lifespan=lifespan,
        default_response_class=ORJSONResponse,
    )

    register_middlewares(app)
    register_exception_handlers(app)
    register_routes(app)

    return app


# ------------------------------------------------------------------------------
# Middleware
# ------------------------------------------------------------------------------
def register_middlewares(app: FastAPI):

    # Logging middleware first
    app.add_middleware(RequestLoggingMiddleware)

    # Compression
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    allow_credentials = True
    if settings.CORS_ORIGINS == ["*"]:
        allow_credentials = False

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=allow_credentials,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", settings.API_KEY_HEADER],
    )

    # Trusted hosts
    if settings.TRUSTED_HOSTS:
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=settings.TRUSTED_HOSTS,
        )

    # Security headers
    @app.middleware("http")
    async def security_headers(request: Request, call_next):

        response = await call_next(request)

        headers = response.headers
        headers["X-Content-Type-Options"] = "nosniff"
        headers["X-Frame-Options"] = "DENY"
        headers["X-XSS-Protection"] = "1; mode=block"
        headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if settings.IS_PRODUCTION:
            headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"

        if request.url.path.startswith("/docs") or request.url.path.startswith("/redoc"):
            headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "img-src 'self' https://fastapi.tiangolo.com data:;"
            )
        elif request.url.path.endswith("/generate-report"):
            headers["Content-Security-Policy"] = (
                "default-src 'none'; "
                "script-src 'unsafe-inline'; "
                "style-src 'unsafe-inline'; "
                "img-src data: blob:; "
                "media-src data: blob:; "
                "font-src data:; "
                "base-uri 'none'; "
                "frame-ancestors 'none'; "
                "object-src 'none';"
            )
        else:
            headers["Content-Security-Policy"] = (
                "default-src 'none'; "
                "base-uri 'none'; "
                "frame-ancestors 'none'; "
                "object-src 'none';"
            )

        return response

    @app.middleware("http")
    async def request_size_limit_middleware(request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                max_request_bytes = settings.MAX_ZIP_SIZE_BYTES + (1024 * 1024)
                if int(content_length) > max_request_bytes:
                    raise APIException(
                        error_code=ErrorCode.INVALID_ZIP,
                        message=f"ZIP file exceeds maximum size of {settings.MAX_ZIP_SIZE_MB}MB",
                        status_code=413,
                        category=ErrorCategory.VALIDATION,
                        severity=ErrorSeverity.WARNING,
                    )
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content=APIException(
                        error_code=ErrorCode.VALIDATION_ERROR,
                        message="Invalid Content-Length header",
                        status_code=400,
                        category=ErrorCategory.VALIDATION,
                        severity=ErrorSeverity.WARNING,
                    ).to_dict()
                )
            except APIException as exc:
                return JSONResponse(
                    status_code=exc.status_code,
                    content=exc.to_dict(),
                    headers=exc.headers
                )

        return await call_next(request)

    # Rate limiting
    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):

        if settings.RATE_LIMIT_ENABLED:
            try:
                await rate_limiter.check_rate_limit(request)
            except APIException as exc:
                return JSONResponse(
                    status_code=exc.status_code,
                    content=exc.to_dict(),
                    headers=exc.headers
                )

        return await call_next(request)


# ------------------------------------------------------------------------------
# Exception Handlers
# ------------------------------------------------------------------------------
def register_exception_handlers(app: FastAPI):

    app.add_exception_handler(APIException, api_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):

        api_exc = APIException(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="Request validation failed",
            status_code=422,
            category=ErrorCategory.VALIDATION,
            severity=ErrorSeverity.WARNING,
            details={"errors": exc.errors()},
        )

        logger.warning(
            "Request validation failed",
            extra={
                "path": request.url.path,
                "errors": exc.errors(),
            },
        )

        return JSONResponse(
            status_code=api_exc.status_code,
            content=api_exc.to_dict(),
        )


# ------------------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------------------
def register_routes(app: FastAPI):

    # Public endpoints
    app.include_router(
        health.router,
        tags=["Health"],
    )

    # Protected endpoints
    app.include_router(
        report.router,
        tags=["Reports"],
        dependencies=[Security(verify_api_key)],
    )


# ------------------------------------------------------------------------------
# Create App
# ------------------------------------------------------------------------------
app = create_app()
