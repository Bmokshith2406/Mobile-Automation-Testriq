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
from starlette.responses import Response

from app.core.config import get_settings
from app.core.health import increment_error_metric, increment_request_metric
from app.core.logging import logger, reset_log_context, set_log_context
from app.core.metrics import Metrics

settings = get_settings()


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

        logger.debug(
            "request_started",
            extra={
                "method": request.method,
                "path": request.url.path,
            },
        )

        try:
            response = await call_next(request)
        except Exception:
            duration_seconds = time.perf_counter() - start_time
            Metrics.record_request(request.method, request.url.path, 500, duration_seconds)
            Metrics.record_error(request.method, request.url.path, "500")
            increment_request_metric()
            increment_error_metric()
            reset_log_context(context_token)
            raise

        duration_seconds = time.perf_counter() - start_time
        duration_ms = round(duration_seconds * 1000, 2)

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Correlation-ID"] = correlation_id
        response.headers["X-Trace-ID"] = trace_id

        Metrics.record_request(
            request.method,
            request.url.path,
            response.status_code,
            duration_seconds,
        )

        if response.status_code >= 500:
            Metrics.record_error(request.method, request.url.path, str(response.status_code))
            increment_error_metric()

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
