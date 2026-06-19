from __future__ import annotations
from typing import Optional, Dict, Any, List
from app.core.exceptions.base import RepairEngineError, ErrorCode

class InvalidInputError(RepairEngineError):
    """Raised when request input is invalid."""
    
    def __init__(
        self,
        message: str = "Invalid input",
        details: Optional[Dict[str, Any]] = None,
        errors: Optional[List[Dict[str, Any]]] = None,
    ):
        super().__init__(
            message=message,
            error_code=ErrorCode.INVALID_INPUT,
            status_code=400,
            details=details,
            errors=errors,
        )


class MissingRequiredFieldError(RepairEngineError):
    """Raised when a required field is missing."""
    
    def __init__(
        self,
        field: str,
        message: Optional[str] = None,
    ):
        super().__init__(
            message=message or f"Missing required field: {field}",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD,
            status_code=400,
            details={"field": field},
        )


class InvalidStepInputError(RepairEngineError):
    """
    Raised when the step input JSON is malformed,
    incomplete, or semantically invalid.
    """
    
    def __init__(
        self,
        message: str = "Invalid step input",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            error_code=ErrorCode.INVALID_FORMAT,
            status_code=400,
            details=details,
        )


class AuthenticationError(RepairEngineError):
    """Base class for authentication errors."""
    
    def __init__(
        self,
        message: str = "Authentication required",
        error_code: ErrorCode = ErrorCode.UNAUTHORIZED,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            status_code=401,
        )


class InvalidAPIKeyError(AuthenticationError):
    """Raised when API key is invalid."""
    
    def __init__(self, message: str = "Invalid API key"):
        super().__init__(
            message=message,
            error_code=ErrorCode.INVALID_API_KEY,
        )


class ExpiredAPIKeyError(AuthenticationError):
    """Raised when API key has expired."""
    
    def __init__(self, message: str = "API key has expired"):
        super().__init__(
            message=message,
            error_code=ErrorCode.EXPIRED_API_KEY,
        )


class AuthorizationError(RepairEngineError):
    """Raised when user lacks required permissions."""
    
    def __init__(
        self,
        message: str = "Insufficient permissions",
        required_scopes: Optional[List[str]] = None,
    ):
        super().__init__(
            message=message,
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            status_code=403,
            details={"required_scopes": required_scopes} if required_scopes else None,
        )


class RateLimitExceededError(RepairEngineError):
    """Raised when rate limit is exceeded."""
    
    def __init__(
        self,
        message: str = "Rate limit exceeded",
        retry_after: int = 60,
        limit: Optional[int] = None,
        remaining: int = 0,
    ):
        super().__init__(
            message=message,
            error_code=ErrorCode.RATE_LIMIT_EXCEEDED,
            status_code=429,
            details={
                "limit": limit,
                "remaining": remaining,
            } if limit else None,
            retry_after=retry_after,
        )


class ResourceNotFoundError(RepairEngineError):
    """Raised when a requested resource is not found."""
    
    def __init__(
        self,
        resource_type: str,
        resource_id: str,
        message: Optional[str] = None,
    ):
        super().__init__(
            message=message or f"{resource_type} not found: {resource_id}",
            error_code=ErrorCode.NOT_FOUND,
            status_code=404,
            details={
                "resource_type": resource_type,
                "resource_id": resource_id,
            },
        )


class ConflictError(RepairEngineError):
    """Raised when there's a resource conflict."""
    
    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            error_code=ErrorCode.CONFLICT,
            status_code=409,
            details=details,
        )


class ArtifactValidationError(RepairEngineError):
    """
    Raised when required artifacts (screenshot, DOM snapshot, etc.)
    are missing, invalid, or exceed constraints.
    """
    
    def __init__(
        self,
        message: str = "Artifact validation failed",
        artifact_type: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        full_details = details or {}
        if artifact_type:
            full_details["artifact_type"] = artifact_type
        
        super().__init__(
            message=message,
            error_code=ErrorCode.ARTIFACT_VALIDATION_FAILED,
            status_code=422,
            details=full_details,
        )


class UnsupportedFailureTypeError(RepairEngineError):
    """
    Raised when the detected failure type cannot be handled
    by the current repair strategies.
    """
    
    def __init__(
        self,
        failure_type: str,
        message: Optional[str] = None,
        supported_types: Optional[List[str]] = None,
    ):
        super().__init__(
            message=message or f"Unsupported failure type: {failure_type}",
            error_code=ErrorCode.UNSUPPORTED_FAILURE_TYPE,
            status_code=422,
            details={
                "failure_type": failure_type,
                "supported_types": supported_types,
            } if supported_types else {"failure_type": failure_type},
        )
