# app/core/exceptions.py

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
import logging
from typing import Any, Optional
from datetime import datetime, timezone

logger = logging.getLogger("exceptions")


def _error_body(
    code: str,
    message: str,
    error_type: str,
    request_id: Optional[str] = None,
) -> dict:
    """Canonical machine-readable error envelope."""
    return {
        "error": {
            "code": code,
            "message": message,
            "type": error_type,
            "request_id": request_id or "-",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    }

# --------------------------------------------------
# Custom Exceptions
# --------------------------------------------------

class ScriptGeneratorException(Exception):
    """Base exception for the application."""
    def __init__(self, message: str, status_code: int = 500, details: Optional[Any] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details

class ExtractionError(ScriptGeneratorException):
    """Raised when deterministic and LLM extraction fail."""
    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(message, status_code=422, details=details)

class CodeGenerationError(ScriptGeneratorException):
    """Raised when the generator fails to produce valid script code."""
    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(message, status_code=422, details=details)

class LLMRateLimitError(ScriptGeneratorException):
    """Raised when all LLM providers hit rate limits and cannot recover."""
    def __init__(self, message: str = "LLM providers rate limited", details: Optional[Any] = None):
        super().__init__(message, status_code=429, details=details)

class WebhookDeliveryError(ScriptGeneratorException):
    """Raised when a webhook fails to deliver."""
    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(message, status_code=502, details=details)


# --------------------------------------------------
# Exception Handlers
# --------------------------------------------------

async def custom_exception_handler(request: Request, exc: ScriptGeneratorException):
    request_id = (
        request.headers.get("x-request-id")
        or request.headers.get("x-correlation-id")
    )

    logger.warning(
        "CUSTOM_EXCEPTION | type=%s method=%s path=%s status=%s detail=%s request_id=%s",
        type(exc).__name__,
        request.method,
        request.url.path,
        exc.status_code,
        exc.message,
        request_id or "-",
    )

    _CODE_MAP = {
        "ExtractionError": "EXTRACTION_FAILED",
        "CodeGenerationError": "GENERATION_FAILED",
        "LLMRateLimitError": "LLM_RATE_LIMITED",
        "WebhookDeliveryError": "WEBHOOK_FAILED",
    }
    code = _CODE_MAP.get(type(exc).__name__, "INTERNAL_ERROR")

    return JSONResponse(
        status_code=exc.status_code,
        content=_error_body(code, exc.message, type(exc).__name__, request_id),
        headers={"X-Request-ID": request_id} if request_id else None,
    )


async def global_exception_handler(request: Request, exc: Exception):
    request_id = (
        request.headers.get("x-request-id")
        or request.headers.get("x-correlation-id")
    )

    # Preserve FastAPI HTTPExceptions
    if isinstance(exc, HTTPException):
        logger.warning(
            "HTTP_EXCEPTION | method=%s path=%s status=%s detail=%s request_id=%s",
            request.method,
            request.url.path,
            exc.status_code,
            exc.detail,
            request_id or "-",
        )

        _STATUS_CODES = {
            400: "BAD_REQUEST",
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            413: "PAYLOAD_TOO_LARGE",
            422: "VALIDATION_FAILED",
            429: "RATE_LIMITED",
            500: "INTERNAL_ERROR",
            502: "BAD_GATEWAY",
            503: "SERVICE_UNAVAILABLE",
            504: "GATEWAY_TIMEOUT",
        }
        code = _STATUS_CODES.get(exc.status_code, "HTTP_ERROR")

        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(code, str(exc.detail), "HTTPException", request_id),
            headers={"X-Request-ID": request_id} if request_id else None,
        )

    # Unhandled exceptions
    logger.error(
        "UNHANDLED_EXCEPTION | method=%s path=%s request_id=%s",
        request.method,
        request.url.path,
        request_id or "-",
        exc_info=True,
    )

    return JSONResponse(
        status_code=500,
        content=_error_body("INTERNAL_ERROR", "Internal Server Error", "UnhandledException", request_id),
        headers={"X-Request-ID": request_id} if request_id else None,
    )

