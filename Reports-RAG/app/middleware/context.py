"""Request context and error handling middleware."""

from typing import Callable
from uuid import uuid4
import random
import time

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.config import settings
from app.core.errors import ProductionError, internal_error, rate_limit_error
from app.core.logging import get_logger, reset_log_context, set_log_context
from app.core.metrics import Metrics
from app.core.rate_limit import get_limiter

logger = get_logger(__name__)

RATE_LIMIT_EXEMPT_PATHS = {
    "/",
    "/health",
    "/health/live",
    "/health/ready",
    "/health/deep",
    "/metrics",
    "/metrics/json",
    "/docs",
    "/openapi.json",
    "/redoc",
}


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        correlation_id = request.headers.get("X-Correlation-ID") or request_id
        trace_id = request.headers.get("X-Trace-ID") or correlation_id
        trace_sampled = settings.ENABLE_TRACING and (
            request.headers.get("X-Trace-Sampled") == "1"
            or random.random() < settings.TRACE_SAMPLE_RATE
        )
        start_time = time.perf_counter()

        request.state.request_id = request_id
        request.state.correlation_id = correlation_id
        request.state.trace_id = trace_id
        request.state.trace_sampled = trace_sampled

        context_token = set_log_context(
            {
                "request_id": request_id,
                "correlation_id": correlation_id,
                "trace_id": trace_id,
            }
        )
        if trace_sampled:
            Metrics.record_trace_sampled()

        client_ip = "unknown"
        if settings.TRUST_FORWARDED_IP:
            forwarded = request.headers.get("X-Forwarded-For", "")
            if forwarded:
                client_ip = forwarded.split(",")[0].strip()
        if client_ip == "unknown" or not client_ip:
            client_ip = request.client.host if request.client else "unknown"

        client_id = client_ip
        limiter = get_limiter()
        active_request_recorded = False
        response: Response | None = None

        try:
            if limiter.enabled and request.url.path not in RATE_LIMIT_EXEMPT_PATHS:
                if not limiter.is_allowed(client_id):
                    error = rate_limit_error(retry_after=settings.RATE_LIMIT_WINDOW_SECONDS)
                    response = JSONResponse(
                        status_code=error.status_code,
                        content=error.detail,
                        headers=error.headers,
                    )
                    response.headers["X-RateLimit-Remaining"] = "0"
                    return response

            Metrics.ACTIVE_REQUESTS.inc()
            active_request_recorded = True
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Correlation-ID"] = correlation_id
            response.headers["X-Trace-ID"] = trace_id

            remaining = limiter.get_remaining(client_id)
            if remaining is not None:
                response.headers["X-RateLimit-Remaining"] = str(remaining)

            return response
        finally:
            duration_seconds = time.perf_counter() - start_time
            duration_ms = round(duration_seconds * 1000, 2)

            status_code = response.status_code if response is not None else 500
            Metrics.record_request(
                request.method,
                request.url.path,
                status_code,
                duration_seconds,
            )
            if status_code >= 400:
                Metrics.record_error(request.method, request.url.path, status_code)

            if active_request_recorded:
                Metrics.ACTIVE_REQUESTS.dec()

            logger.info(
                "request_completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                    "trace_sampled": trace_sampled,
                },
            )
            reset_log_context(context_token)


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            return await call_next(request)
        except ProductionError as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content=exc.detail,
                headers=exc.headers,
            )
        except Exception as exc:
            request_id = getattr(request.state, "request_id", str(uuid4()))
            logger.exception(
                "Unhandled exception in request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "request_id": request_id,
                    "error": str(exc),
                },
            )
            err = internal_error(request_id=request_id)
            return JSONResponse(
                status_code=err.status_code,
                content=err.detail,
                headers=err.headers,
            )
