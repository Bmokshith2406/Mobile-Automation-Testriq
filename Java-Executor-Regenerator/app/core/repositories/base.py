from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional, List
from app.models.database import RepairRecord, ExecutionRecord, FailurePattern

class Repository(ABC):
    """Abstract base class representing the data store."""
    
    @abstractmethod
    async def save_repair(self, record: RepairRecord) -> str:
        pass
        
    @abstractmethod
    async def get_repair(self, record_id: str) -> Optional[RepairRecord]:
        pass
        
    @abstractmethod
    async def get_repairs_by_step(self, step_id: str, limit: int = 100) -> List[RepairRecord]:
        pass
        
    @abstractmethod
    async def get_recent_repairs(self, limit: int = 100) -> List[RepairRecord]:
        pass
        
    @abstractmethod
    async def count_repairs(self, outcome: Optional[str] = None) -> int:
        pass
        
    @abstractmethod
    async def save_execution(self, record: ExecutionRecord) -> str:
        pass
        
    @abstractmethod
    async def get_execution(self, record_id: str) -> Optional[ExecutionRecord]:
        pass
        
    @abstractmethod
    async def get_executions_by_run(self, run_id: str) -> List[ExecutionRecord]:
        pass
        
    @abstractmethod
    async def get_recent_executions(self, limit: int = 100) -> List[ExecutionRecord]:
        pass
        
    @abstractmethod
    async def track_failure_pattern(self, fingerprint: str, error_type: str, error_pattern: str) -> FailurePattern:
        pass
        
    @abstractmethod
    async def get_failure_pattern(self, fingerprint: str) -> Optional[FailurePattern]:
        pass
        
    @abstractmethod
    async def get_top_failure_patterns(self, limit: int = 10) -> List[FailurePattern]:
        pass
        
    @abstractmethod
    async def get_repair_stats(self) -> dict:
        pass
        
    @abstractmethod
    async def get_execution_stats(self) -> dict:
        pass

    async def initialize_indexes(self) -> None:
        """Initialize search/TTL indexes. Default no-op."""
        pass
