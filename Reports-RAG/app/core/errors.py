"""Standardized application errors."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict

from app.core.logging import get_log_context, get_logger

logger = get_logger(__name__)


class ErrorCode(str, Enum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    DUPLICATE_ENTRY = "DUPLICATE_ENTRY"
    NOT_FOUND = "NOT_FOUND"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    CONFLICT = "CONFLICT"
    DATABASE_ERROR = "DATABASE_ERROR"
    EXTERNAL_API_ERROR = "EXTERNAL_API_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    request_id: str
    timestamp: str
    details: Optional[Dict[str, Any]] = None
    retry_after: Optional[int] = None
    correlation_id: Optional[str] = None


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ErrorDetail


class ProductionError(HTTPException):
    """Structured exception that preserves the active request context."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        status_code: int = 400,
        details: Optional[Dict[str, Any]] = None,
        retry_after: Optional[int] = None,
        request_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        context = get_log_context()
        self.request_id = request_id or context.get("request_id") or str(uuid4())
        self.correlation_id = correlation_id or context.get("correlation_id") or self.request_id
        self.error_code = code
        self.error_message = message
        self.error_details = details or {}
        self.retry_after = retry_after
        self.timestamp = datetime.now(timezone.utc).isoformat()

        error_detail = ErrorDetail(
            code=code.value,
            message=message,
            request_id=self.request_id,
            timestamp=self.timestamp,
            details=self.error_details or None,
            retry_after=retry_after,
            correlation_id=self.correlation_id,
        )
        response_body = ErrorResponse(error=error_detail)

        response_headers: Dict[str, str] = {
            "X-Request-ID": self.request_id,
            "X-Correlation-ID": self.correlation_id,
        }
        if retry_after is not None:
            response_headers["Retry-After"] = str(retry_after)
        if headers:
            response_headers.update(headers)

        super().__init__(
            status_code=status_code,
            detail=response_body.model_dump(mode="json"),
            headers=response_headers,
        )
        self._log_error()

    def _log_error(self) -> None:
        payload: Dict[str, Any] = {
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "status_code": self.status_code,
            "error_code": self.error_code.value,
        }
        if self.error_details:
            payload["details"] = self.error_details

        if self.status_code >= 500:
            logger.error(self.error_message, extra=payload)
        else:
            logger.warning(self.error_message, extra=payload)


def validation_error(
    message: str,
    details: Optional[Dict[str, Any]] = None,
) -> ProductionError:
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
    return ProductionError(
        code=ErrorCode.NOT_FOUND,
        message=message,
        status_code=404,
        details=details,
    )


def rate_limit_error(retry_after: int = 60) -> ProductionError:
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
    return ProductionError(
        code=ErrorCode.INTERNAL_ERROR,
        message=message,
        status_code=500,
        request_id=request_id,
    )
