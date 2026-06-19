from __future__ import annotations
from enum import Enum
from datetime import datetime, UTC
from typing import Optional, Dict, Any, List

class ErrorCode(str, Enum):
    """Standardized error codes for API responses."""
    
    # Input validation errors (400)
    INVALID_INPUT = "INVALID_INPUT"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    INVALID_FORMAT = "INVALID_FORMAT"
    
    # Authentication errors (401)
    UNAUTHORIZED = "UNAUTHORIZED"
    INVALID_API_KEY = "INVALID_API_KEY"
    EXPIRED_API_KEY = "EXPIRED_API_KEY"
    
    # Authorization errors (403)
    FORBIDDEN = "FORBIDDEN"
    INSUFFICIENT_PERMISSIONS = "INSUFFICIENT_PERMISSIONS"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    
    # Resource errors (404, 409)
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    ALREADY_EXISTS = "ALREADY_EXISTS"
    
    # Validation errors (422)
    VALIDATION_ERROR = "VALIDATION_ERROR"
    ARTIFACT_VALIDATION_FAILED = "ARTIFACT_VALIDATION_FAILED"
    UNSUPPORTED_FAILURE_TYPE = "UNSUPPORTED_FAILURE_TYPE"
    
    # Repair-specific errors
    STEP_NOT_REPAIRABLE = "STEP_NOT_REPAIRABLE"
    REPAIR_TIMEOUT = "REPAIR_TIMEOUT"
    MAX_RETRIES_EXCEEDED = "MAX_RETRIES_EXCEEDED"
    circuit_breaker_open = "CIRCUIT_BREAKER_OPEN"  # for lower-case reference
    CIRCUIT_BREAKER_OPEN = "CIRCUIT_BREAKER_OPEN"
    
    # Execution errors
    EXECUTION_FAILED = "EXECUTION_FAILED"
    SANDBOX_VIOLATION = "SANDBOX_VIOLATION"
    SCRIPT_TIMEOUT = "SCRIPT_TIMEOUT"
    
    # External service errors
    LLM_ERROR = "LLM_ERROR"
    LLM_TIMEOUT = "LLM_TIMEOUT"
    LLM_RATE_LIMITED = "LLM_RATE_LIMITED"
    DATABASE_ERROR = "DATABASE_ERROR"
    REDIS_ERROR = "REDIS_ERROR"
    
    # Internal errors (500)
    INTERNAL_ERROR = "INTERNAL_ERROR"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"


class RepairEngineError(Exception):
    """
    Base exception for all Repair Engine errors.
    Provides structured error information for API responses.
    """
    
    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.INTERNAL_ERROR,
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None,
        errors: Optional[List[Dict[str, Any]]] = None,
        retry_after: Optional[int] = None,
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.details = details or {}
        self.errors = errors or []
        self.retry_after = retry_after
        self.timestamp = datetime.now(UTC).isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to API response dictionary."""
        response = {
            "error": {
                "code": self.error_code.value,
                "message": self.message,
                "timestamp": self.timestamp,
            }
        }
        
        if self.details:
            response["error"]["details"] = self.details
        
        if self.errors:
            response["error"]["errors"] = self.errors
        
        if self.retry_after:
            response["error"]["retry_after"] = self.retry_after
        
        return response
