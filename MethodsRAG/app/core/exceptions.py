"""Custom exception classes for the application."""

from fastapi import HTTPException, status
from typing import Any, Optional


class ApplicationException(Exception):
    """Base exception for all application errors."""
    
    def __init__(
        self,
        message: str,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        error_code: str = "INTERNAL_ERROR",
        details: Optional[dict[str, Any]] = None,
    ):
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.details = details or {}
        super().__init__(self.message)


class ValidationError(ApplicationException):
    """Raised when input validation fails."""
    
    def __init__(self, message: str, field: Optional[str] = None, details: Optional[dict] = None):
        super().__init__(
            message=message,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            error_code="VALIDATION_ERROR",
            details={"field": field, **(details or {})}
        )


class FileValidationError(ValidationError):
    """Raised when file validation fails."""
    
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(
            message=message,
            field="file",
            details=details or {}
        )


class SizeExceededError(FileValidationError):
    """Raised when file size exceeds limit."""
    
    def __init__(self, size_mb: float, max_size_mb: int):
        super().__init__(
            message=f"File size {size_mb:.1f}MB exceeds maximum {max_size_mb}MB",
            details={"size_mb": size_mb, "max_size_mb": max_size_mb}
        )


class DatabaseError(ApplicationException):
    """Raised when database operation fails."""
    
    def __init__(self, message: str, operation: Optional[str] = None, details: Optional[dict] = None):
        super().__init__(
            message=message,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="DATABASE_ERROR",
            details={"operation": operation, **(details or {})}
        )


class InvalidObjectIdError(ValidationError):
    """Raised when ObjectId format is invalid."""
    
    def __init__(self, object_id: str):
        super().__init__(
            message=f"Invalid document ID format: {object_id}",
            field="id",
            details={"provided_id": object_id}
        )


class NotFoundError(ApplicationException):
    """Raised when resource is not found."""
    
    def __init__(self, resource: str, identifier: Optional[str] = None, details: Optional[dict] = None):
        message = f"{resource} not found"
        if identifier:
            message += f": {identifier}"
        super().__init__(
            message=message,
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="NOT_FOUND",
            details={"resource": resource, "identifier": identifier, **(details or {})}
        )


class RateLimitError(ApplicationException):
    """Raised when rate limit is exceeded."""
    
    def __init__(self, retry_after: int = 60):
        super().__init__(
            message="Rate limit exceeded. Please try again later.",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            error_code="RATE_LIMIT_EXCEEDED",
            details={"retry_after": retry_after}
        )


class ExternalServiceError(ApplicationException):
    """Raised when external service (Gemini, etc.) fails."""
    
    def __init__(self, service: str, message: str, retry_after: Optional[int] = None, details: Optional[dict] = None):
        super().__init__(
            message=f"{service} service error: {message}",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error_code="EXTERNAL_SERVICE_ERROR",
            details={"service": service, "retry_after": retry_after, **(details or {})}
        )


class TimeoutError(ExternalServiceError):
    """Raised when an operation times out."""
    
    def __init__(self, service: str, timeout_seconds: float):
        super().__init__(
            service=service,
            message=f"Operation timed out after {timeout_seconds}s",
            details={"timeout_seconds": timeout_seconds}
        )


def to_http_exception(exc: ApplicationException) -> HTTPException:
    """Convert ApplicationException to HTTPException."""
    return HTTPException(
        status_code=exc.status_code,
        detail={
            "error": exc.error_code,
            "message": exc.message,
            "details": exc.details if exc.details else None,
        }
    )
