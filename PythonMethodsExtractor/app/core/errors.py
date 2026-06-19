"""
Standardized error handling for production-grade API.
Provides error codes, structured responses, and automatic request tracking.
"""

from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict

from app.core.logging import logger


class ErrorCode(str, Enum):
    """Standard error codes for all API responses."""

    # Client errors (4xx)
    VALIDATION_ERROR = "VALIDATION_ERROR"
    DUPLICATE_ENTRY = "DUPLICATE_ENTRY"
    NOT_FOUND = "NOT_FOUND"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    CONFLICT = "CONFLICT"

    # Server errors (5xx)
    DATABASE_ERROR = "DATABASE_ERROR"
    EXTERNAL_API_ERROR = "EXTERNAL_API_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


class ErrorDetail(BaseModel):
    """Structured error response model."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    request_id: str
    timestamp: str
    details: Optional[Dict[str, Any]] = None
    retry_after: Optional[int] = None
    correlation_id: Optional[str] = None


class ErrorResponse(BaseModel):
    """Complete error response wrapper."""

    model_config = ConfigDict(extra="forbid")

    error: ErrorDetail


class ProductionError(HTTPException):
    """
    Production-ready HTTP exception with structured error responses.
    Automatically tracks request IDs and provides retry guidance.
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        status_code: int = 400,
        details: Optional[Dict[str, Any]] = None,
        retry_after: Optional[int] = None,
        correlation_id: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        self.error_code = code
        self.request_id = str(uuid4())
        self.correlation_id = correlation_id or self.request_id
        self.error_message = message
        self.error_details = details or {}
        self.retry_after = retry_after

        # timezone-aware timestamp
        self.timestamp = datetime.now(timezone.utc).isoformat()

        # Build response
        error_detail = ErrorDetail(
            code=code.value,
            message=message,
            request_id=self.request_id,
            timestamp=self.timestamp,
            details=self.error_details,
            retry_after=retry_after,
            correlation_id=self.correlation_id,
        )

        response_body = ErrorResponse(error=error_detail)

        # Build headers
        response_headers: Dict[str, str] = {}

        if retry_after:
            response_headers["Retry-After"] = str(retry_after)

        response_headers["X-Request-ID"] = self.request_id
        response_headers["X-Correlation-ID"] = self.correlation_id
        if headers:
            response_headers.update(headers)

        super().__init__(
            status_code=status_code,
            detail=response_body.model_dump(),
            headers=response_headers,
        )

        # Log error
        self._log_error()

    def _log_error(self):
        """Log error with appropriate severity."""

        log_payload = {
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "status_code": self.status_code,
            "error_code": self.error_code.value,
        }

        if self.error_details:
            log_payload["details"] = self.error_details

        if self.status_code >= 500:
            logger.error(
                "server_error",
                extra={**log_payload, "message": self.error_message},
            )
        else:
            logger.warning(
                "client_error",
                extra={**log_payload, "message": self.error_message},
            )


# ------------------------------------------------------------------
# Convenience error factory functions
# ------------------------------------------------------------------


def validation_error(
    message: str,
    details: Optional[Dict[str, Any]] = None,
) -> ProductionError:
    """Create a validation error (400)."""
    return ProductionError(
        code=ErrorCode.VALIDATION_ERROR,
        message=message,
        status_code=400,
        details=details,
    )


def not_found_error(
    message: str = "Resource not found",
    details: Optional[Dict[str, Any]] = None,
) -> ProductionError:
    """Create a not found error (404)."""
    return ProductionError(
        code=ErrorCode.NOT_FOUND,
        message=message,
        status_code=404,
        details=details,
    )


def rate_limit_error(retry_after: int = 60) -> ProductionError:
    """Create a rate limit error (429)."""
    return ProductionError(
        code=ErrorCode.RATE_LIMIT_EXCEEDED,
        message="Too many requests. Please wait before retrying.",
        status_code=429,
        retry_after=retry_after,
    )


def unauthorized_error(
    message: str = "Could not validate credentials",
    details: Optional[Dict[str, Any]] = None,
) -> ProductionError:
    return ProductionError(
        code=ErrorCode.UNAUTHORIZED,
        message=message,
        status_code=401,
        details=details,
        headers={"WWW-Authenticate": "Bearer"},
    )


def forbidden_error(
    message: str = "You do not have permission to access this resource",
    details: Optional[Dict[str, Any]] = None,
) -> ProductionError:
    return ProductionError(
        code=ErrorCode.FORBIDDEN,
        message=message,
        status_code=403,
        details=details,
    )


def database_error(
    message: str = "Database operation failed",
    details: Optional[Dict[str, Any]] = None,
) -> ProductionError:
    """Create a database error (503)."""
    return ProductionError(
        code=ErrorCode.DATABASE_ERROR,
        message=message,
        status_code=503,
        details=details,
        retry_after=30,
    )


def external_api_error(
    message: str = "External service failed",
    details: Optional[Dict[str, Any]] = None,
) -> ProductionError:
    """Create an external API error (503)."""
    return ProductionError(
        code=ErrorCode.EXTERNAL_API_ERROR,
        message=message,
        status_code=503,
        details=details,
        retry_after=60,
    )


def internal_error(
    message: str = "An unexpected error occurred",
    request_id: Optional[str] = None,
) -> ProductionError:
    """Create an internal server error (500)."""
    return ProductionError(
        code=ErrorCode.INTERNAL_ERROR,
        message=message,
        status_code=500,
        correlation_id=request_id,
    )
