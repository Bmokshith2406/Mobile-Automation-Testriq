from __future__ import annotations
import uuid
from datetime import datetime, UTC
from typing import Optional, Dict, Any
from dataclasses import dataclass, field

@dataclass
class RepairRecord:
    """Record of a repair operation."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    step_id: str = ""
    original_code: str = ""
    repaired_code: Optional[str] = None
    intent: str = ""
    error_type: str = ""
    error_message: str = ""
    outcome: str = ""  # success, not_repairable, timeout, model_error
    duration_ms: int = 0
    model_name: str = ""
    llm_calls: int = 0
    tokens_used: int = 0
    request_id: Optional[str] = None
    client_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "step_id": self.step_id,
            "original_code": self.original_code,
            "repaired_code": self.repaired_code,
            "intent": self.intent,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "outcome": self.outcome,
            "duration_ms": self.duration_ms,
            "model_name": self.model_name,
            "llm_calls": self.llm_calls,
            "tokens_used": self.tokens_used,
            "request_id": self.request_id,
            "client_id": self.client_id,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }

@dataclass
class ExecutionRecord:
    """Record of a script execution."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str = ""
    script_path: str = ""
    script_hash: str = ""
    status: str = ""  # passed, failed, timeout, error
    exit_code: int = 0
    duration_ms: int = 0
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    repairs_attempted: int = 0
    repairs_successful: int = 0
    request_id: Optional[str] = None
    client_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "script_path": self.script_path,
            "script_hash": self.script_hash,
            "status": self.status,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "repairs_attempted": self.repairs_attempted,
            "repairs_successful": self.repairs_successful,
            "request_id": self.request_id,
            "client_id": self.client_id,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }

@dataclass
class FailurePattern:
    """Tracked failure pattern for analysis."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    fingerprint: str = ""  # Hash of error signature
    error_type: str = ""
    error_pattern: str = ""
    occurrences: int = 1
    last_seen: datetime = field(default_factory=lambda: datetime.now(UTC))
    repair_success_rate: float = 0.0
    avg_repair_time_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
