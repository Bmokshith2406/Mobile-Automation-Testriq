from __future__ import annotations
from typing import Optional, Dict, Any
from app.core.exceptions.base import RepairEngineError, ErrorCode

class ExecutionError(RepairEngineError):
    """Base class for script execution errors."""
    
    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.EXECUTION_FAILED,
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            status_code=status_code,
            details=details,
        )


class SandboxViolationError(ExecutionError):
    """Raised when script violates sandbox restrictions."""
    
    def __init__(
        self,
        message: str = "Sandbox security violation",
        violation_type: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        full_details = details or {}
        if violation_type:
            full_details["violation_type"] = violation_type
        
        super().__init__(
            message=message,
            error_code=ErrorCode.SANDBOX_VIOLATION,
            status_code=403,
            details=full_details,
        )


class ScriptTimeoutError(ExecutionError):
    """Raised when script execution times out."""
    
    def __init__(
        self,
        message: str = "Script execution timed out",
        timeout_seconds: Optional[int] = None,
        script_path: Optional[str] = None,
    ):
        super().__init__(
            message=message,
            error_code=ErrorCode.SCRIPT_TIMEOUT,
            status_code=504,
            details={
                "timeout_seconds": timeout_seconds,
                "script_path": script_path,
            },
        )
