import time
import sentry_sdk
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.logger import get_logger, set_request_id, set_trace_id

logger = get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Enterprise-grade HTTP request/response logging middleware."""

    async def dispatch(self, request: Request, call_next):
        start_time = time.perf_counter()

        # ------------------------------------------------------------------
        # Correlation IDs
        # ------------------------------------------------------------------
        request_id = request.headers.get("X-Request-ID")
        trace_id = request.headers.get("X-Trace-ID")

        request_id = set_request_id(request_id)
        trace_id = set_trace_id(trace_id)
        
        if request_id:
            sentry_sdk.set_tag("request_id", request_id)
        if trace_id:
            sentry_sdk.set_tag("trace_id", trace_id)

        try:
            response = await call_next(request)
        except Exception as exc:
            process_time = (time.perf_counter() - start_time) * 1000

            logger.critical(
                "Unhandled exception during request",
                extra={
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "method": request.method,
                    "path": request.url.path,
                    "process_time_ms": round(process_time, 2),
                },
                exc_info=True,
            )
            raise

        process_time = (time.perf_counter() - start_time) * 1000

        log_payload = {
            "request_id": request_id,
            "trace_id": trace_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "process_time_ms": round(process_time, 2),
            "client_ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent"),
        }

        # Slow request detection
        if process_time > 5000:
            logger.warning("Slow request detected", extra=log_payload)
        else:
            logger.info("HTTP request", extra=log_payload)

        # Attach IDs to response headers
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Trace-ID"] = trace_id

        return response
