from __future__ import annotations
import logging
from datetime import datetime, UTC
from typing import Optional, List, Dict
from app.models.database import RepairRecord, ExecutionRecord, FailurePattern
from app.core.repositories.base import Repository

logger = logging.getLogger("database")

class InMemoryRepository(Repository):
    """
    In-memory implementation of the repository pattern.
    Used when no database is configured.
    """
    
    def __init__(self, max_records: int = 10000):
        self.max_records = max_records
        self._repairs: List[RepairRecord] = []
        self._executions: List[ExecutionRecord] = []
        self._patterns: Dict[str, FailurePattern] = {}
    
    # --------------------------------------------------
    # Repair Records
    # --------------------------------------------------
    
    async def save_repair(self, record: RepairRecord) -> str:
        self._repairs.append(record)
        if len(self._repairs) > self.max_records:
            self._repairs = self._repairs[-self.max_records:]
        logger.debug("Saved repair record: %s", record.id)
        return record.id
    
    async def get_repair(self, record_id: str) -> Optional[RepairRecord]:
        for record in self._repairs:
            if record.id == record_id:
                return record
        return None
    
    async def get_repairs_by_step(self, step_id: str, limit: int = 100) -> List[RepairRecord]:
        results = [r for r in self._repairs if r.step_id == step_id]
        return sorted(results, key=lambda r: r.created_at, reverse=True)[:limit]
    
    async def get_recent_repairs(self, limit: int = 100) -> List[RepairRecord]:
        return sorted(self._repairs, key=lambda r: r.created_at, reverse=True)[:limit]
    
    async def count_repairs(self, outcome: Optional[str] = None) -> int:
        if outcome:
            return sum(1 for r in self._repairs if r.outcome == outcome)
        return len(self._repairs)
    
    # --------------------------------------------------
    # Execution Records
    # --------------------------------------------------
    
    async def save_execution(self, record: ExecutionRecord) -> str:
        self._executions.append(record)
        if len(self._executions) > self.max_records:
            self._executions = self._executions[-self.max_records:]
        logger.debug("Saved execution record: %s", record.id)
        return record.id
    
    async def get_execution(self, record_id: str) -> Optional[ExecutionRecord]:
        for record in self._executions:
            if record.id == record_id:
                return record
        return None
    
    async def get_executions_by_run(self, run_id: str) -> List[ExecutionRecord]:
        return [r for r in self._executions if r.run_id == run_id]
    
    async def get_recent_executions(self, limit: int = 100) -> List[ExecutionRecord]:
        return sorted(self._executions, key=lambda r: r.created_at, reverse=True)[:limit]
    
    # --------------------------------------------------
    # Failure Patterns
    # --------------------------------------------------
    
    async def track_failure_pattern(self, fingerprint: str, error_type: str, error_pattern: str) -> FailurePattern:
        if fingerprint in self._patterns:
            pattern = self._patterns[fingerprint]
            pattern.occurrences += 1
            pattern.last_seen = datetime.now(UTC)
        else:
            pattern = FailurePattern(
                fingerprint=fingerprint,
                error_type=error_type,
                error_pattern=error_pattern,
            )
            self._patterns[fingerprint] = pattern
        return pattern
    
    async def get_failure_pattern(self, fingerprint: str) -> Optional[FailurePattern]:
        return self._patterns.get(fingerprint)
    
    async def get_top_failure_patterns(self, limit: int = 10) -> List[FailurePattern]:
        patterns = list(self._patterns.values())
        return sorted(patterns, key=lambda p: p.occurrences, reverse=True)[:limit]
    
    # --------------------------------------------------
    # Statistics
    # --------------------------------------------------
    
    async def get_repair_stats(self) -> dict:
        total = len(self._repairs)
        if total == 0:
            return {"total": 0, "successes": 0, "success_rate": 0.0, "avg_duration_ms": 0.0, "total_tokens": 0}
        
        successes = sum(1 for r in self._repairs if r.outcome == "success")
        total_duration = sum(r.duration_ms for r in self._repairs)
        
        return {
            "total": total,
            "successes": successes,
            "success_rate": successes / total,
            "avg_duration_ms": total_duration / total,
            "total_tokens": sum(r.tokens_used for r in self._repairs),
        }
    
    async def get_execution_stats(self) -> dict:
        total = len(self._executions)
        if total == 0:
            return {"total": 0, "passes": 0, "pass_rate": 0.0, "avg_duration_ms": 0.0, "total_repairs_attempted": 0, "total_repairs_successful": 0}
        
        passes = sum(1 for r in self._executions if r.status == "passed")
        total_duration = sum(r.duration_ms for r in self._executions)
        
        return {
            "total": total,
            "passes": passes,
            "pass_rate": passes / total,
            "avg_duration_ms": total_duration / total,
            "total_repairs_attempted": sum(r.repairs_attempted for r in self._executions),
            "total_repairs_successful": sum(r.repairs_successful for r in self._executions),
        }
