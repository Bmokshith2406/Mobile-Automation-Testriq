from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime, timezone
import uuid


# ------------------------------------------------------------------------------
# Error Classification
# ------------------------------------------------------------------------------

class ErrorCategory(str, Enum):
    VALIDATION = "validation"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    RATE_LIMIT = "rate_limit"
    DEPENDENCY = "dependency"
    TIMEOUT = "timeout"
    BUSINESS = "business"
    INTERNAL = "internal"


class ErrorSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# ------------------------------------------------------------------------------
# Error Codes
# ------------------------------------------------------------------------------

class ErrorCode(str, Enum):
    # Validation
    VALIDATION_ERROR = "ERR_VALIDATION_ERROR"

    # ZIP / Upload
    INVALID_ZIP = "ERR_INVALID_ZIP"
    ZIP_EXTRACTION_FAILED = "ERR_ZIP_EXTRACTION_FAILED"
    MISSING_ARTIFACTS = "ERR_MISSING_ARTIFACTS"

    # AI
    AI_PROVIDER_ERROR = "ERR_AI_PROVIDER_ERROR"
    GEMINI_API_ERROR = "ERR_GEMINI_API_ERROR"
    AI_TIMEOUT = "ERR_AI_TIMEOUT"

    # PDF / Report
    PDF_GENERATION_FAILED = "ERR_PDF_GENERATION_FAILED"

    # Rate Limiting
    RATE_LIMIT_EXCEEDED = "ERR_RATE_LIMIT_EXCEEDED"

    # Auth / Permission
    UNAUTHORIZED = "ERR_UNAUTHORIZED"
    FORBIDDEN = "ERR_FORBIDDEN"

    # Generic
    INTERNAL_SERVER_ERROR = "ERR_INTERNAL_SERVER_ERROR"
    SERVICE_UNAVAILABLE = "ERR_SERVICE_UNAVAILABLE"


# ------------------------------------------------------------------------------
# API Exception (Enterprise Grade)
# ------------------------------------------------------------------------------

class APIException(Exception):
    """
    Production-grade API exception.

    Features:
    - Unique error ID
    - UTC timestamp (timezone-aware)
    - Structured logging support
    - Retry flag
    - Safe serialization
    - Optional internal context (not exposed externally)
    """

    def __init__(
        self,
        *,
        error_code: ErrorCode,
        message: str,
        status_code: int,
        category: ErrorCategory,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        details: Optional[Dict[str, Any]] = None,
        retryable: bool = False,
        context: Optional[Dict[str, Any]] = None,  # Internal debugging only
        headers: Optional[Dict[str, str]] = None,
    ):
        self.id = str(uuid.uuid4())
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        self.category = category
        self.severity = severity
        self.details = details or {}
        self.retryable = retryable
        self.context = context or {}
        self.headers = headers or {}

        super().__init__(self.message)

    # --------------------------------------------------------------------------
    # Public Response
    # --------------------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "status": "error",
            "error_code": self.error_code.value,
            "message": self.message,
            "category": self.category.value,
            "severity": self.severity.value,
            "retryable": self.retryable,
            "details": self.details,
        }

    # --------------------------------------------------------------------------
    # Structured Log Payload
    # --------------------------------------------------------------------------
    def to_log_dict(self) -> Dict[str, Any]:
        return {
            "error_id": self.id,
            "error_code": self.error_code.value,
            "category": self.category.value,
            "severity": self.severity.value,
            "retryable": self.retryable,
            "context": self.context,
            "details": self.details,
        }

    # --------------------------------------------------------------------------
    # Factory Helpers (Cleaner Usage)
    # --------------------------------------------------------------------------
    @classmethod
    def unauthorized(cls, message: str = "Unauthorized"):
        return cls(
            error_code=ErrorCode.UNAUTHORIZED,
            message=message,
            status_code=401,
            category=ErrorCategory.AUTHENTICATION,
            severity=ErrorSeverity.WARNING,
        )

    @classmethod
    def forbidden(cls, message: str = "Forbidden"):
        return cls(
            error_code=ErrorCode.FORBIDDEN,
            message=message,
            status_code=403,
            category=ErrorCategory.AUTHORIZATION,
            severity=ErrorSeverity.WARNING,
        )

    @classmethod
    def validation_error(cls, details: Dict[str, Any]):
        return cls(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="Request validation failed",
            status_code=422,
            category=ErrorCategory.VALIDATION,
            severity=ErrorSeverity.WARNING,
            details=details,
        )

    @classmethod
    def internal_error(cls, message: str = "Internal server error"):
        return cls(
            error_code=ErrorCode.INTERNAL_SERVER_ERROR,
            message=message,
            status_code=500,
            category=ErrorCategory.INTERNAL,
            severity=ErrorSeverity.CRITICAL,
        )
