"""
FastAPI Application Entry Point

Features:
- API Key protection (global)
- Rate limiting
- Health checks
- Metrics endpoint
- OpenTelemetry tracing
- Circuit breaker status
- Proper middleware ordering
"""

import logging
import time
from contextlib import asynccontextmanager
import contextvars
from uuid import uuid4

request_id_context = contextvars.ContextVar("request_id", default="-")

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.security import APIKeyHeader
from fastapi.openapi.utils import get_openapi

# Internal App Imports
from app.core.config import get_settings
from app.core.exceptions import global_exception_handler, custom_exception_handler, ScriptGeneratorException
from app.core.llm import LLMProviderFactory
from app.core.metrics import get_metrics
from app.core.tracing import init_tracing
from app.middleware.audit import audit_middleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.api_key import APIKeyMiddleware
from app.core.cleanup import run_cleanup_loop
from app.routes.batch import router as batch_router
from app.routes.cost import router as cost_router
from app.routes.generate import router as generate_router
from app.routes.health import router as health_router
from app.routes.generate_matrix import router as generate_matrix_router
# Note: Ensure these routers exist in your file structure
from app.routes.metrics import router as metrics_router
from app.routes.stream import router as stream_router
from app.routes.validate import router as validate_router
from app.routes.admin import router as admin_router
from app.core.tracing import add_span_attributes, get_tracer
from app.services.webhook_notifier import get_webhook_notifier as _get_webhook_notifier

settings = get_settings()
api_key_header = APIKeyHeader(
    name=settings.API_KEY_HEADER,
    auto_error=False,
)
logger = logging.getLogger("app")

# -------------------------
# Logging Setup
# -------------------------

import json as _json


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_data["exc_info"] = self.formatException(record.exc_info)
        return _json.dumps(log_data)


class RequestContextFilter(logging.Filter):
    def filter(self, record):
        record.request_id = request_id_context.get()
        return True

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | [%(request_id)s] | %(message)s"
log_level = getattr(logging, settings.LOG_LEVEL)

root_logger = logging.getLogger()
root_logger.setLevel(log_level)

if not any(getattr(handler, "name", "") == "app_console" for handler in root_logger.handlers):
    console_handler = logging.StreamHandler()
    console_handler.name = "app_console"
    console_handler.setLevel(log_level)
    console_handler.addFilter(RequestContextFilter())
    if settings.LOG_FORMAT == "json":
        console_handler.setFormatter(JSONFormatter())
    else:
        console_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root_logger.addHandler(console_handler)

if settings.LOG_TO_FILE and not any(getattr(handler, "name", "") == "app_file" for handler in root_logger.handlers):
    import os
    from pathlib import Path as _Path
    _log_dir = _Path(__file__).resolve().parent.parent / "logs"
    os.makedirs(_log_dir, exist_ok=True)
    file_handler = logging.FileHandler(str(_log_dir / "app.log"), mode="a", encoding="utf-8")
    file_handler.name = "app_file"
    file_handler.setLevel(log_level)
    file_handler.addFilter(RequestContextFilter())
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root_logger.addHandler(file_handler)


class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, max_bytes: int):
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")

        if content_length:
            try:
                if int(content_length) > self.max_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": "Request body too large"},
                    )
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "Invalid Content-Length header"},
                )

        # Track actual bytes read for clients that omit Content-Length
        body_size = 0
        original_receive = request._receive

        async def limited_receive():
            nonlocal body_size
            message = await original_receive()
            if message.get("type") == "http.request":
                body = message.get("body", b"")
                body_size += len(body)
                if body_size > self.max_bytes:
                    raise RuntimeError("Request body too large")
            return message

        request._receive = limited_receive
        try:
            return await call_next(request)
        except RuntimeError as e:
            if "too large" in str(e):
                return JSONResponse(status_code=413, content={"detail": "Request body too large"})
            raise


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        req_id = request.headers.get("x-request-id") or request.headers.get("x-correlation-id") or str(uuid4())[:8]
        token = request_id_context.set(req_id)
        
        metrics = get_metrics()
        metrics.record_request_start()

        start_time = time.perf_counter()

        try:
            response = await call_next(request)
            success = response.status_code < 400
        except Exception:
            success = False
            raise
        finally:
            duration_ms = (time.perf_counter() - start_time) * 1000
            metrics.record_request_end(success, duration_ms)
            request_id_context.reset(token)

        return response


class TracingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):

        tracer = get_tracer()

        with tracer.start_as_current_span(f"{request.method} {request.url.path}"):
            add_span_attributes(
                {
                    "http.method": request.method,
                    "http.url": str(request.url),
                    "http.route": request.url.path,
                }
            )

            response = await call_next(request)

            add_span_attributes(
                {
                    "http.status_code": response.status_code,
                }
            )

            return response

# -------------------------
# Lifespan Context
# -------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Application starting...")

    if settings.TRACING_ENABLED:
        init_tracing(
            service_name=settings.APP_NAME,
            endpoint=settings.TRACING_ENDPOINT,
        )
        logger.info("OpenTelemetry tracing enabled")

    primary, fallbacks = LLMProviderFactory.initialize_providers()

    if not primary and not fallbacks:
        logger.critical("No LLM providers available!")
        raise RuntimeError("At least one LLM provider must be configured")

    logger.info(
        "LLM providers ready | primary=%s | fallbacks=%d",
        primary.provider_type if primary else "none",
        len(fallbacks),
    )

    import asyncio
    logger.info("Application startup complete")
    cleanup_task = asyncio.create_task(run_cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        await asyncio.gather(cleanup_task, return_exceptions=True)
        await _get_webhook_notifier().close()
        logger.info("Application shutdown complete")

# -------------------------
# FastAPI App Initialization
# -------------------------

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    description="LLM-powered Automation Test Script Generator",
    lifespan=lifespan,
    # Docs UI disabled in production; OpenAPI JSON always accessible at /openapi.json
    # so clients can still generate SDKs and validate schemas.
    docs_url="/docs" if settings.ENV != "production" else None,
    redoc_url="/redoc" if settings.ENV != "production" else None,
    openapi_url="/openapi.json",  # always on regardless of ENV
)

# -------------------------------------------------------
# Middleware Stack
#
# IMPORTANT — FastAPI add_middleware() is LIFO (last added = outermost = first to execute).
# To control execution order, list middleware innermost-first, outermost-last.
#
# TRUE execution order (request flows through top → bottom):
#   1. APIKeyMiddleware        ← rejects unauthenticated requests immediately
#   2. TracingMiddleware       ← attach trace context
#   3. MetricsMiddleware       ← record timing
#   4. AuditMiddleware         ← log every request/response
#   5. RateLimitMiddleware     ← enforce per-IP limits (after auth, before work)
#   6. MaxBodySizeMiddleware   ← reject oversized payloads
#   7. CORSMiddleware          ← add CORS headers (innermost, runs last)
# -------------------------------------------------------

# 7. CORS — added first → runs LAST (innermost, wraps the app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["POST", "GET", "DELETE"],
    allow_headers=["Content-Type", "X-Request-ID", settings.API_KEY_HEADER],
)

# 6. Body Size Protection — rejects oversized requests
app.add_middleware(
    MaxBodySizeMiddleware,
    max_bytes=settings.MAX_REQUEST_SIZE_BYTES,
)

# 5. Rate Limiting — applied after auth, before heavy processing
if settings.RATE_LIMIT_ENABLED:
    app.add_middleware(
        RateLimitMiddleware,
        requests_per_window=settings.RATE_LIMIT_REQUESTS,
        window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
    )

# 4. Audit Logging
app.add_middleware(BaseHTTPMiddleware, dispatch=audit_middleware)

# 3. Metrics
app.add_middleware(MetricsMiddleware)

# 2. Tracing (optional)
if settings.TRACING_ENABLED:
    app.add_middleware(TracingMiddleware)

# 1. API Key — added last → runs FIRST (outermost), rejects unauthenticated requests
app.add_middleware(APIKeyMiddleware)


# -------------------------
# Exception Handlers
# -------------------------

app.add_exception_handler(ScriptGeneratorException, custom_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)

# -------------------------
# Route Registration
# -------------------------

V1 = "/v1"

app.include_router(generate_router, prefix=f"{V1}/generate", tags=["Generation"])
app.include_router(generate_matrix_router, prefix=f"{V1}/generate/matrix", tags=["Generation"])
app.include_router(health_router, prefix="/health", tags=["Health"])
app.include_router(metrics_router, prefix=f"{V1}/metrics", tags=["Monitoring"])
app.include_router(stream_router, prefix=f"{V1}/stream", tags=["Streaming"])
app.include_router(batch_router, prefix=f"{V1}/batch", tags=["Batch Processing"])
app.include_router(cost_router, prefix=f"{V1}/cost", tags=["Cost Estimation"])
app.include_router(validate_router, prefix=f"{V1}/validate", tags=["Validation"])
app.include_router(admin_router, prefix=f"{V1}/admin", tags=["Admin"])

@app.get("/", include_in_schema=False)
async def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.VERSION,
        "api_version": "v1",
        "created_by": settings.CREATED_BY,
        "docs": "/docs" if settings.ENV != "production" else "disabled",
        "openapi": "/openapi.json",
        "endpoints": {
            "generate": "/v1/generate/",
            "batch": "/v1/batch/",
            "stream": "/v1/stream/generate",
            "validate": "/v1/validate/",
            "cost": "/v1/cost/estimate",
            "metrics": "/v1/metrics/",
            "health": "/health/",
            "admin": "/v1/admin/",
        },
    }
    
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    openapi_schema["components"]["securitySchemes"] = {
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": settings.API_KEY_HEADER,
        }
    }

    # Apply security globally
    openapi_schema["security"] = [{"ApiKeyAuth": []}]

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi

