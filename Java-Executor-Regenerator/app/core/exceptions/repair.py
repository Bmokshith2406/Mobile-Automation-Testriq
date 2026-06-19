from __future__ import annotations
from typing import Optional, Dict, Any
from app.core.exceptions.base import RepairEngineError, ErrorCode

class StepRepairError(RepairEngineError):
    """Base class for all step repair domain errors."""
    
    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.INTERNAL_ERROR,
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            status_code=status_code,
            details=details,
        )


class StepNotRepairableError(StepRepairError):
    """
    Raised when a step has been deterministically analyzed
    and rejected as non-repairable after bounded attempts.
    """

    def __init__(
        self,
        message: str,
        step_id: Optional[str] = None,
        attempts: int = 0,
        details: Optional[Dict[str, Any]] = None,
    ):
        full_details = details or {}
        if step_id:
            full_details["step_id"] = step_id
        full_details["attempts"] = attempts
        
        super().__init__(
            message=message,
            error_code=ErrorCode.STEP_NOT_REPAIRABLE,
            status_code=409,
            details=full_details,
        )


class RepairTimeoutError(StepRepairError):
    """Raised when repair operation times out."""
    
    def __init__(
        self,
        message: str = "Repair operation timed out",
        timeout_seconds: Optional[int] = None,
        step_id: Optional[str] = None,
    ):
        super().__init__(
            message=message,
            error_code=ErrorCode.REPAIR_TIMEOUT,
            status_code=504,
            details={
                "timeout_seconds": timeout_seconds,
                "step_id": step_id,
            },
        )


class MaxRetriesExceededError(StepRepairError):
    """Raised when maximum retry attempts are exceeded."""
    
    def __init__(
        self,
        message: str = "Maximum retry attempts exceeded",
        max_retries: int = 3,
        step_id: Optional[str] = None,
    ):
        super().__init__(
            message=message,
            error_code=ErrorCode.MAX_RETRIES_EXCEEDED,
            status_code=409,
            details={
                "max_retries": max_retries,
                "step_id": step_id,
            },
        )


class CircuitBreakerOpenError(StepRepairError):
    """Raised when circuit breaker is open."""
    
    def __init__(
        self,
        message: str = "Service temporarily unavailable",
        circuit_name: Optional[str] = None,
        retry_after: int = 60,
    ):
        super().__init__(
            message=message,
            error_code=ErrorCode.CIRCUIT_BREAKER_OPEN,
            status_code=503,
            details={"circuit_name": circuit_name} if circuit_name else None,
        )
        self.retry_after = retry_after
