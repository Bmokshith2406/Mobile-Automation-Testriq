"""
Request context middleware for tracking request IDs and correlation across services.
Adds X-Request-ID and X-Correlation-ID headers to all responses.
"""
from typing import Callable
from uuid import uuid4
import random
import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings
from app.core.errors import rate_limit_error
from app.core.health import increment_request_metric
from app.core.logging import logger, reset_log_context, set_log_context
from app.core.metrics import Metrics
from app.core.rate_limit import get_limiter

settings = get_settings()
RATE_LIMIT_EXEMPT_PATHS = {
    "/",
    "/health",
    "/health/live",
    "/health/ready",
    "/health/deep",
    "/docs",
    "/openapi.json",
    "/redoc",
}


class RequestContextMiddleware(BaseHTTPMiddleware):
    """
    Middleware that adds request/correlation IDs for distributed tracing.
    Automatically generates IDs if not provided in headers.
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Extract or generate request ID
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        correlation_id = request.headers.get("X-Correlation-ID") or request_id
        trace_id = request.headers.get("X-Trace-ID") or correlation_id
        trace_sampled = settings.ENABLE_TRACING and (
            request.headers.get("X-Trace-Sampled") == "1"
            or random.random() < settings.TRACE_SAMPLE_RATE
        )
        start_time = time.perf_counter()
        
        # Store in request state for access in handlers
        request.state.request_id = request_id
        request.state.correlation_id = correlation_id
        request.state.trace_id = trace_id
        request.state.trace_sampled = trace_sampled

        context_token = set_log_context({
            "request_id": request_id,
            "correlation_id": correlation_id,
            "trace_id": trace_id,
        })
        if trace_sampled:
            Metrics.record_trace_sampled()
        
        client_ip = "unknown"
        if settings.TRUST_FORWARDED_IP:
            forwarded = request.headers.get("X-Forwarded-For", "")
            if forwarded:
                client_ip = forwarded.split(",")[0].strip()
        if client_ip == "unknown" or not client_ip:
            client_ip = request.client.host if request.client else "unknown"

        # Log request
        logger.debug(
            "request_started",
            extra={
                "method": request.method,
                "path": request.url.path,
                "client_ip": client_ip,
                "trace_sampled": trace_sampled,
            }
        )

        client_id = client_ip
        limiter = get_limiter()

        if request.url.path not in RATE_LIMIT_EXEMPT_PATHS:
            if not limiter.is_allowed(client_id):
                duration_seconds = time.perf_counter() - start_time
                error = rate_limit_error()
                response = JSONResponse(
                    status_code=error.status_code,
                    content=error.detail,
                    headers=error.headers,
                )
                response.headers["X-RateLimit-Remaining"] = "0"
                Metrics.record_request(
                    request.method,
                    request.url.path,
                    error.status_code,
                    duration_seconds,
                )
                Metrics.record_error(request.method, request.url.path, str(error.status_code))
                increment_request_metric()
                reset_log_context(context_token)
                return response

        try:
            response = await call_next(request)
        except Exception:
            duration_seconds = time.perf_counter() - start_time
            Metrics.record_request(
                request.method,
                request.url.path,
                500,
                duration_seconds,
            )
            Metrics.record_error(request.method, request.url.path, "500")
            increment_request_metric()
            reset_log_context(context_token)
            raise

        duration_seconds = time.perf_counter() - start_time
        duration_ms = round(duration_seconds * 1000, 2)

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Correlation-ID"] = correlation_id
        response.headers["X-Trace-ID"] = trace_id
        response.headers["X-RateLimit-Remaining"] = str(limiter.get_remaining(client_id))

        Metrics.record_request(
            request.method,
            request.url.path,
            response.status_code,
            duration_seconds,
        )
        if response.status_code >= 500:
            Metrics.record_error(request.method, request.url.path, str(response.status_code))
        increment_request_metric()

        logger.info(
            "request_completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "trace_sampled": trace_sampled,
            },
        )

        reset_log_context(context_token)
        return response


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """Middleware that catches unhandled exceptions and converts to structured errors."""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            response = await call_next(request)
            return response

        except Exception as exc:
            from app.core.errors import internal_error, ProductionError
            from app.core.health import increment_error_metric
            from fastapi.responses import JSONResponse

            request_id = getattr(request.state, "request_id", str(uuid4()))

            # If already structured error → return directly
            if isinstance(exc, ProductionError):
                increment_error_metric()

                return JSONResponse(
                    status_code=exc.status_code,
                    content=exc.detail,
                    headers=exc.headers
                )

            # Unexpected exception
            logger.error(
                f"Unhandled exception in {request.method} {request.url.path}",
                exc_info=True,
                extra={"request_id": request_id}
            )

            increment_error_metric()

            err = internal_error(request_id=request_id)

            return JSONResponse(
                status_code=err.status_code,
                content=err.detail,
                headers=err.headers
            )
