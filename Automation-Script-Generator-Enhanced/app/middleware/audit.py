# app/middleware/audit.py

import time
import logging
from fastapi import Request

logger = logging.getLogger("audit")


def _resolve_client_ip(request: Request) -> str:
    """
    Extract the real client IP, honouring TRUST_FORWARDED_IP when set.

    When the service sits behind a trusted reverse proxy (nginx, ELB, etc.)
    and TRUST_FORWARDED_IP=true, reads X-Forwarded-For / X-Real-IP headers.
    Otherwise falls back to the direct TCP peer address.
    """
    try:
        from app.core.config import get_settings
        settings = get_settings()
        trust = settings.TRUST_FORWARDED_IP
    except Exception:
        trust = False

    if trust:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip

    return request.client.host if request.client else "unknown"


async def audit_middleware(request: Request, call_next):
    # Skip noisy health-check endpoints
    if request.url.path.endswith("/health"):
        return await call_next(request)

    start = time.perf_counter()
    response = None

    request_id = (
        request.headers.get("x-request-id")
        or request.headers.get("x-correlation-id")
    )

    client_ip = _resolve_client_ip(request)

    try:
        response = await call_next(request)

        # Propagate request ID for downstream tracing
        if request_id:
            response.headers["X-Request-ID"] = request_id

        return response

    finally:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        status_code = getattr(response, "status_code", 500)

        logger.info(
            "method=%s path=%s status=%s duration_ms=%s client_ip=%s request_id=%s",
            request.method,
            request.url.path,
            status_code,
            duration_ms,
            client_ip,
            request_id or "-",
        )
