from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

class ExecutionOutcome(str, Enum):
    """Execution outcome status."""
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    SANDBOX_VIOLATION = "sandbox_violation"
    VALIDATION_ERROR = "validation_error"
    UNKNOWN = "unknown"

@dataclass
class ExecutionResult:
    """Result of a script execution."""
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool
    command: List[str]
    working_dir: str
    artifacts_dir: Optional[str]
    script_path: str
    run_id: str
    semantic_status: str  # "passed" | "failed" | "unknown"
    outcome: ExecutionOutcome = ExecutionOutcome.UNKNOWN
    error: str = ""
    step_results: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_ms": self.duration_ms,
            "timed_out": self.timed_out,
            "command": self.command,
            "working_dir": self.working_dir,
            "artifacts_dir": self.artifacts_dir,
            "script_path": self.script_path,
            "run_id": self.run_id,
            "semantic_status": self.semantic_status,
            "outcome": self.outcome.value,
            "error": self.error,
            "step_results": self.step_results,
            "metadata": self.metadata,
        }
