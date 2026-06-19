"""
Playwright Step Repair Engine - Main Application

Production-Grade FastAPI Application with:
- API Authentication
- Rate Limiting
- Metrics & Tracing
- Health Checks
- Structured Logging
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.middleware.base import BaseHTTPMiddleware
from contextlib import asynccontextmanager
from fastapi.openapi.utils import get_openapi
import logging
import sys
import time

from app.routes.repair import router as repair_router
from app.routes.executor import router as executor_router
from app.routes.health import router as health_router
from app.routes.metrics import router as metrics_router
from app.middleware import audit_middleware
from app.core.exceptions import (
    global_exception_handler,
    StepNotRepairableError,
)
from app.core.config import get_settings
from app.core.security import (
    APIKeyAuthMiddleware,
    RateLimitMiddleware,
    APIKeyValidator,
    RateLimiter,
)
from app.core.metrics import MetricsRegistry, get_metrics
from app.core.health import HealthChecker, get_health_checker, HealthStatus
from app.core.database import get_database


# ==================================================
# Settings (MUST COME FIRST)
# ==================================================

settings = get_settings()


# ==================================================
# Logging setup (AFTER settings)
# ==================================================

class PrettyFormatter(logging.Formatter):
    """
    Enterprise-grade, clean, and highly readable console log formatter.
    """
    # ANSI escape sequences
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    UNDERLINE = "\033[4m"
    
    # Colors
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    GRAY = "\033[90m"

    # Status indicators (single emoji representing the outcome/status of the log)
    LEVEL_INDICATORS = {
        "DEBUG": "🔍",
        "INFO": "✨",
        "WARNING": "⚠️",
        "ERROR": "❌",
        "CRITICAL": "🚨",
    }
    
    # Level badges with formatting
    LEVEL_BADGES = {
        "DEBUG": f"\033[36mDEBUG\033[0m",
        "INFO": f"\033[32mINFO \033[0m",
        "WARNING": f"\033[33mWARN \033[0m",
        "ERROR": f"\033[31m\033[1mERROR\033[0m",
        "CRITICAL": f"\033[31m\033[1m\033[4mCRIT \033[0m",
    }

    # Short display names for loggers to align them cleanly
    LOGGER_NAME_MAP = {
        "uvicorn.error": "uvicorn",
        "uvicorn.access": "access",
        "api.repair": "api-repair",
        "api.executor": "api-exec",
        "cir.builder": "cir-build",
        "atomic_normalizer": "normalizer",
    }

    def format(self, record):
        lvl = record.levelname
        indicator = self.LEVEL_INDICATORS.get(lvl, "📝")
        if record.name.startswith("uvicorn.access"):
            indicator = "🌐"
        badge = self.LEVEL_BADGES.get(lvl, f"{lvl:<5}")
        
        # Format time: HH:MM:SS
        asctime = self.formatTime(record, "%H:%M:%S")
        time_str = f"{self.GRAY}{asctime}{self.RESET}"
        
        # Format logger/component name with fixed-width alignment
        logger_name = record.name
        display_name = self.LOGGER_NAME_MAP.get(logger_name, logger_name.split(".")[-1])
        component_str = f"{self.BLUE}{self.BOLD}[{display_name:<10}]{self.RESET}"
        
        # Format message
        record.message = record.getMessage()
        message_str = record.message
        
        # Colorize access log or standard messages
        if logger_name == "uvicorn.access" and record.args and len(record.args) >= 5:
            try:
                client = record.args[0]
                method = record.args[1]
                path = record.args[2]
                status = str(record.args[4])
                
                status_val = int(status)
                if status_val >= 500:
                    status_str = f"{self.BOLD}{self.RED}{status}{self.RESET}"
                elif status_val >= 400:
                    status_str = f"{self.RED}{status}{self.RESET}"
                elif status_val >= 300:
                    status_str = f"{self.CYAN}{status}{self.RESET}"
                else:
                    status_str = f"{self.GREEN}{status}{self.RESET}"
                    
                method_str = f"{self.BOLD}{self.BLUE}{method}{self.RESET}"
                message_str = f"Client {self.GRAY}{client}{self.RESET} -> {method_str} {self.CYAN}{path}{self.RESET} -> {status_str}"
            except Exception:
                pass
        else:
            if lvl in ("ERROR", "CRITICAL"):
                message_str = f"{self.BOLD}{self.RED}{message_str}{self.RESET}"
            elif lvl == "WARNING":
                message_str = f"{self.YELLOW}{message_str}{self.RESET}"
        
        # Format extra keys (req_id, run_id, etc.)
        extras = getattr(record, "extras", {})
        extras_list = []
        if isinstance(extras, dict):
            corr_id = extras.get("correlation_id", None)
            if corr_id:
                extras_list.append(f"req_id={corr_id}")
            for k, v in extras.items():
                if k not in ("correlation_id",) and v is not None:
                    extras_list.append(f"{k}={v}")
        
        extras_str = ""
        if extras_list:
            extras_str = f" {self.GRAY}|{self.RESET} {self.DIM}{self.CYAN}{' '.join(extras_list)}{self.RESET}"
            
        # Assemble clean, aligned log line
        log_line = f"{indicator} {time_str} {component_str} {badge} - {message_str}{extras_str}"
        
        # Clean tracebacks with vertical line prefix
        if record.exc_info:
            exc_text = self.formatException(record.exc_info)
            colored_exc = "\n".join(f"{self.RED}│{self.RESET} {self.GRAY}{line}{self.RESET}" for line in exc_text.splitlines())
            log_line += f"\n{colored_exc}"
        elif record.exc_text:
            colored_exc = "\n".join(f"{self.RED}│{self.RESET} {self.GRAY}{line}{self.RESET}" for line in record.exc_text.splitlines())
            log_line += f"\n{colored_exc}"
            
        return log_line


RESERVED_KEYS = {
    "name", "msg", "args", "levelname", "levelno", "pathname",
    "filename", "module", "exc_info", "exc_text", "stack_info",
    "lineno", "funcName", "created", "msecs", "relativeCreated",
    "thread", "threadName", "processName", "process",
    "taskName", "color_message", "task_name"
}


class ExtraFieldsFilter(logging.Filter):
    def filter(self, record):
        extras = {
            k: v for k, v in record.__dict__.items()
            if k not in RESERVED_KEYS
        }
        from app.core.utils import get_correlation_id
        corr_id = get_correlation_id()
        if corr_id:
            extras["correlation_id"] = corr_id
        record.extras = extras
        return True


class JSONFormatter(logging.Formatter):
    """
    Structured logging formatter that outputs logs as single-line JSON.
    """
    def format(self, record):
        import json
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        elif record.exc_text:
            log_data["exception"] = record.exc_text

        # Inject correlation_id or extra fields
        extras = getattr(record, "extras", None)
        if isinstance(extras, dict):
            for k, v in extras.items():
                log_data[k] = v

        return json.dumps(log_data)


class ConsoleFormatter(logging.Formatter):
    """
    Clean human-readable formatter for local console debugging.
    """
    def format(self, record):
        extras = getattr(record, "extras", {})
        corr_id = extras.get("correlation_id", None) if isinstance(extras, dict) else None
        corr_str = f" | req_id={corr_id}" if corr_id else ""
        
        record.message = record.getMessage()
        asctime = self.formatTime(record, self.datefmt)
        log_line = f"{asctime} | {record.levelname} | {record.name} | {record.message}{corr_str}".strip()
        
        if record.exc_info:
            log_line += "\n" + self.formatException(record.exc_info)
        elif record.exc_text:
            log_line += "\n" + record.exc_text
        return log_line


def apply_logging_format():
    """Apply the configured log formatter and filters to all active loggers."""
    log_level = getattr(logging, settings.LOG_LEVEL)
    if settings.LOG_FORMAT_MODE == "JSON":
        formatter = JSONFormatter()
    elif settings.LOG_FORMAT_MODE == "PRETTY":
        formatter = PrettyFormatter()
    else:
        formatter = ConsoleFormatter(datefmt="%Y-%m-%d %H:%M:%S")

    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.setFormatter(formatter)
        if not any(isinstance(f, ExtraFieldsFilter) for f in handler.filters):
            handler.addFilter(ExtraFieldsFilter())

    loggers = [
        "cir.builder", "llm", "atomic_normalizer",
        "api.repair", "api.executor", "app",
        "security", "metrics", "health", "tracing",
        "uvicorn", "uvicorn.error", "uvicorn.access"
    ]
    for logger_name in loggers:
        l = logging.getLogger(logger_name)
        l.setLevel(log_level)
        if logger_name.startswith("uvicorn"):
            l.propagate = True
            l.handlers.clear()
        else:
            for handler in l.handlers:
                handler.setFormatter(formatter)
                if not any(isinstance(f, ExtraFieldsFilter) for f in handler.filters):
                    handler.addFilter(ExtraFieldsFilter())


def setup_logging():
    """Initial logging configuration on import."""
    log_level = getattr(logging, settings.LOG_LEVEL)
    logging.basicConfig(
        level=log_level,
        stream=sys.stdout,
    )
    apply_logging_format()


setup_logging()
logger = logging.getLogger("app")


# -------------------------
# Safety Middleware
# -------------------------

class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    """Middleware to limit request body size."""

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

        return await call_next(request)


# -------------------------
# Metrics Middleware
# -------------------------

class MetricsMiddleware(BaseHTTPMiddleware):
    """Middleware to collect request metrics."""

    async def dispatch(self, request: Request, call_next):
        if not get_settings().ENABLE_METRICS:
            return await call_next(request)

        metrics = get_metrics()

        path = request.url.path
        method = request.method

        metrics.http_requests_in_progress.inc(method=method, path=path)
        start = time.perf_counter()

        try:
            response = await call_next(request)
            duration = time.perf_counter() - start

            metrics.http_requests_total.inc(
                method=method,
                path=path,
                status=str(response.status_code),
            )
            metrics.http_request_duration_seconds.observe(
                duration,
                method=method,
                path=path,
            )

            return response

        except Exception:
            duration = time.perf_counter() - start

            metrics.http_requests_total.inc(
                method=method,
                path=path,
                status="500",
            )
            metrics.http_request_duration_seconds.observe(
                duration,
                method=method,
                path=path,
            )
            raise

        finally:
            metrics.http_requests_in_progress.dec(method=method, path=path)


# -------------------------
# Lifespan
# -------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""

    apply_logging_format()
    logger.info("Starting application...")

    if not settings.effective_api_keys:
        if settings.is_production:
            logger.critical("GOOGLE_API_KEY is not configured")
            raise RuntimeError("GOOGLE_API_KEY must be set in production")
        else:
            logger.warning("GOOGLE_API_KEY is not configured - LLM features will fail")

    db = get_database()
    await db.initialize()

    health_checker = get_health_checker()

    if settings.ENABLE_METRICS:
        MetricsRegistry.get_instance()
        logger.info("Metrics enabled")

    logger.info(
        "Application started | version=%s | env=%s | api_auth=%s | rate_limiting=%s | metrics=%s",
        settings.VERSION,
        settings.ENV,
        settings.ENABLE_API_AUTH,
        settings.ENABLE_RATE_LIMITING,
        settings.ENABLE_METRICS,
    )

    health_checker.mark_startup_complete()

    yield

    logger.info("Shutting down application...")
    await db.close()
    logger.info("Application shutdown complete")


# -------------------------
# App
# -------------------------

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    description="Production-grade multi-framework test step repair engine with self-healing capabilities",
    lifespan=lifespan,
    docs_url="/docs" if settings.is_development else None,
    redoc_url="/redoc" if settings.is_development else None,
    openapi_url="/openapi.json" if settings.is_development else None,
)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    # Add API Key security scheme
    openapi_schema["components"]["securitySchemes"] = {
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": settings.API_KEY_HEADER,
        }
    }

    # Apply globally (all routes)
    openapi_schema["security"] = [{"ApiKeyAuth": []}]

    app.openapi_schema = openapi_schema
    return app.openapi_schema


if settings.ENABLE_API_AUTH and settings.is_development:
    app.openapi = custom_openapi

# -------------------------
# Middleware (deterministic order)
# Execution order: last added = first executed
# -------------------------

# CORS (outermost)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=settings.CORS_ALLOW_METHODS,
    allow_headers=settings.CORS_ALLOW_HEADERS,
)

# Body size protection
app.add_middleware(
    MaxBodySizeMiddleware,
    max_bytes=settings.MAX_REQUEST_SIZE_BYTES,
)

# API key authentication
app.add_middleware(
    APIKeyAuthMiddleware,
    validator=APIKeyValidator(),
)

# Rate limiting
app.add_middleware(
    RateLimitMiddleware,
    limiter=RateLimiter(
        requests_per_minute=settings.RATE_LIMIT_REQUESTS_PER_MINUTE,
        burst_size=settings.RATE_LIMIT_BURST_SIZE,
    ),
)

# Metrics
app.add_middleware(MetricsMiddleware)

# Audit (innermost — closest to app logic)
app.middleware("http")(audit_middleware)


# -------------------------
# DOMAIN EXCEPTION HANDLERS
# -------------------------

@app.exception_handler(StepNotRepairableError)
async def step_not_repairable_handler(
    request: Request,
    exc: StepNotRepairableError,
):
    logger.info(
        "STEP NOT REPAIRABLE | path=%s | reason=%s",
        request.url.path,
        str(exc),
    )
    return JSONResponse(
        status_code=409,
        content={
            "error": "STEP_NOT_REPAIRABLE",
            "reason": str(exc),
        },
    )


app.add_exception_handler(Exception, global_exception_handler)


# -------------------------
# Routes
# -------------------------

app.include_router(repair_router, prefix="/repair", tags=["repair"])
app.include_router(executor_router, prefix="/executor", tags=["executor"])
app.include_router(health_router, prefix="/health", tags=["health"])
app.include_router(metrics_router, prefix="/metrics", tags=["observability"])


# -------------------------
# Info Endpoint
# -------------------------

@app.get("/", tags=["info"])
@app.get("/info", tags=["info"])
async def info_endpoint():
    curr_settings = get_settings()
    return {
        "name": curr_settings.APP_NAME,
        "version": curr_settings.VERSION,
        "created_by": curr_settings.CREATED_BY,
        "environment": curr_settings.ENV,
        "features": {
            "api_auth": curr_settings.ENABLE_API_AUTH,
            "rate_limiting": curr_settings.ENABLE_RATE_LIMITING,
            "metrics": curr_settings.ENABLE_METRICS,
            "tracing": curr_settings.ENABLE_TRACING,
            "multimodal": curr_settings.ENABLE_MULTIMODAL,
            "self_healing": curr_settings.ENABLE_SELF_HEALING,
        },
    }