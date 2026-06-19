from __future__ import annotations

import logging
from datetime import datetime, UTC
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse

from app.core.exceptions.base import ErrorCode, RepairEngineError
from app.core.exceptions.api import (
    InvalidInputError,
    MissingRequiredFieldError,
    InvalidStepInputError,
    AuthenticationError,
    InvalidAPIKeyError,
    ExpiredAPIKeyError,
    AuthorizationError,
    RateLimitExceededError,
    ResourceNotFoundError,
    ConflictError,
    ArtifactValidationError,
    UnsupportedFailureTypeError,
)
from app.core.exceptions.repair import (
    StepRepairError,
    StepNotRepairableError,
    RepairTimeoutError,
    MaxRetriesExceededError,
    CircuitBreakerOpenError,
)
from app.core.exceptions.executor import (
    ExecutionError,
    SandboxViolationError,
    ScriptTimeoutError,
)

logger = logging.getLogger("exceptions")


async def global_exception_handler(request: Request, exc: Exception):
    """
    Global exception handler for FastAPI.
    Converts all exceptions to structured JSON responses.
    """
    request_id = (
        request.headers.get("x-request-id")
        or request.headers.get("x-correlation-id")
    )

    if isinstance(exc, RepairEngineError):
        log_level = logging.WARNING if exc.status_code < 500 else logging.ERROR
        logger.log(
            log_level,
            "%s | method=%s path=%s status=%s request_id=%s",
            exc.error_code.value,
            request.method,
            request.url.path,
            exc.status_code,
            request_id or "-",
        )
        
        response = exc.to_dict()
        headers = {"X-Request-ID": request_id} if request_id else {}
        
        if exc.retry_after:
            headers["Retry-After"] = str(exc.retry_after)
        
        return JSONResponse(
            status_code=exc.status_code,
            content=response,
            headers=headers,
        )

    if isinstance(exc, HTTPException):
        logger.warning(
            "HTTP_EXCEPTION | method=%s path=%s status=%s detail=%s request_id=%s",
            request.method,
            request.url.path,
            exc.status_code,
            exc.detail,
            request_id or "-",
        )

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": "HTTP_ERROR",
                    "message": exc.detail,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            },
            headers={"X-Request-ID": request_id} if request_id else None,
        )

    logger.error(
        "UNHANDLED_EXCEPTION | method=%s path=%s request_id=%s error=%s",
        request.method,
        request.url.path,
        request_id or "-",
        str(exc),
        exc_info=True,
    )

    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": ErrorCode.INTERNAL_ERROR.value,
                "message": "Internal Server Error",
                "timestamp": datetime.now(UTC).isoformat(),
            }
        },
        headers={"X-Request-ID": request_id} if request_id else None,
    )


__all__ = [
    "ErrorCode",
    "RepairEngineError",
    "InvalidInputError",
    "MissingRequiredFieldError",
    "InvalidStepInputError",
    "AuthenticationError",
    "InvalidAPIKeyError",
    "ExpiredAPIKeyError",
    "AuthorizationError",
    "RateLimitExceededError",
    "ResourceNotFoundError",
    "ConflictError",
    "ArtifactValidationError",
    "UnsupportedFailureTypeError",
    "StepRepairError",
    "StepNotRepairableError",
    "RepairTimeoutError",
    "MaxRetriesExceededError",
    "CircuitBreakerOpenError",
    "ExecutionError",
    "SandboxViolationError",
    "ScriptTimeoutError",
    "global_exception_handler",
]
