"""
Audit Middleware - Production Grade

Responsibilities:
- Request timing
- Correlation / request ID propagation
- High-level outcome visibility (repair + executor aware)
- Structured logging
- Tracing context propagation
"""

import time
import logging
import uuid
from fastapi import Request

from app.core.config import get_settings
from app.core.tracing import get_tracer, SpanKind

logger = logging.getLogger("audit")
settings = get_settings()


async def audit_middleware(request: Request, call_next):
    """
    Production-grade audit middleware with tracing support.
    """
    
    # Skip noisy endpoints
    skip_paths = {"/health", "/health/live", "/health/ready", "/metrics"}
    if request.url.path in skip_paths:
        return await call_next(request)

    start = time.perf_counter()
    response = None

    # --------------------------------------------------
    # Correlation ID (support multiple header formats)
    # --------------------------------------------------
    request_id = (
        request.headers.get("x-request-id")
        or request.headers.get("x-correlation-id")
        or (request.headers.get("traceparent", "").split("-")[1] if "-" in request.headers.get("traceparent", "") else None)
        or uuid.uuid4().hex[:12]
    )

    # Make request ID available everywhere
    request.state.request_id = request_id

    # Set correlation ID context variable
    from app.core.utils import set_correlation_id, correlation_id_ctx
    token = set_correlation_id(request_id)

    # Client identification
    client_ip = _get_client_ip(request)
    client_id = getattr(request.state, "api_key_hash", None)

    # Detect presence of attachments safely
    content_type = request.headers.get("content-type", "")
    has_attachment = content_type.lower().startswith("multipart/")

    # --------------------------------------------------
    # Tracing context
    # --------------------------------------------------
    tracer = get_tracer()
    trace_id, parent_span_id = tracer.extract_context(dict(request.headers))
    
    if trace_id:
        request.state.trace_id = trace_id
        request.state.parent_span_id = parent_span_id

    try:
        # Execute request with tracing
        with tracer.start_span(
            name=f"{request.method} {request.url.path}",
            kind=SpanKind.SERVER,
            attributes={
                "http.method": request.method,
                "http.url": str(request.url),
                "http.route": request.url.path,
                "http.client_ip": client_ip,
                "request_id": request_id,
            },
        ) as span:
            response = await call_next(request)

            # Add response attributes to span
            if span and response:
                span.set_attribute("http.status_code", response.status_code)

            # Propagate request ID to response
            if response is not None:
                response.headers["X-Request-ID"] = request_id
                
                # Add trace headers for distributed tracing
                if settings.ENABLE_TRACING:
                    response.headers["X-Trace-ID"] = span.trace_id if span else request_id

            return response

    except Exception as exc:
        # Log exception (will be re-raised)
        logger.error(
            "REQUEST_EXCEPTION | method=%s path=%s request_id=%s error=%s",
            request.method,
            request.url.path,
            request_id,
            str(exc),
        )
        raise

    finally:
        correlation_id_ctx.reset(token)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        status_code = getattr(response, "status_code", 500) if response else 500
        path = request.url.path

        # --------------------------------------------------
        # Semantic outcome classification (route-aware)
        # --------------------------------------------------
        outcome = _classify_outcome(path, status_code)

        # Structured log entry
        logger.info(
            "REQUEST | method=%s path=%s status=%s outcome=%s duration_ms=%s client_ip=%s client_id=%s attachment=%s request_id=%s",
            request.method,
            path,
            status_code,
            outcome,
            duration_ms,
            client_ip,
            client_id or "-",
            has_attachment,
            request_id,
        )


def _get_client_ip(request: Request) -> str:
    """
    Extract client IP address, handling proxies.
    """
    settings = get_settings()
    if settings.TRUST_FORWARDED_IP:
        # Check X-Forwarded-For header (from load balancers/proxies)
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # First IP in the list is the original client
            return forwarded.split(",")[0].strip()
        
        # Check X-Real-IP header (Nginx)
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
    
    # Fall back to direct client
    if request.client:
        return request.client.host
    
    return "unknown"


def _classify_outcome(path: str, status_code: int) -> str:
    """
    Classify request outcome based on route and status code.
    """
    if path.startswith("/repair"):
        if status_code < 400:
            return "REPAIR_SUCCESS"
        elif status_code == 409:
            return "REPAIR_NOT_REPAIRABLE"
        elif status_code == 429:
            return "REPAIR_RATE_LIMITED"
        elif status_code in (400, 422):
            return "REPAIR_INVALID_INPUT"
        elif status_code == 504:
            return "REPAIR_TIMEOUT"
        else:
            return "REPAIR_ERROR"

    elif path.startswith("/executor"):
        if status_code < 400:
            return "EXECUTION_SUCCESS"
        elif status_code == 429:
            return "EXECUTION_RATE_LIMITED"
        elif status_code in (400, 422):
            return "EXECUTION_INVALID_INPUT"
        elif status_code == 504:
            return "EXECUTION_TIMEOUT"
        else:
            return "EXECUTION_FAILURE"

    elif path.startswith("/health"):
        return "HEALTH_CHECK"

    elif path == "/metrics":
        return "METRICS"

    else:
        if status_code < 400:
            return "SUCCESS"
        elif status_code == 401:
            return "UNAUTHORIZED"
        elif status_code == 403:
            return "FORBIDDEN"
        elif status_code == 404:
            return "NOT_FOUND"
        elif status_code == 429:
            return "RATE_LIMITED"
        else:
            return "ERROR"
