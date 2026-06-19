from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Optional, Dict
from app.executors.models import ExecutionResult

class BaseExecutor(ABC):
    """Abstract base class for all execution engines."""
    
    @abstractmethod
    async def execute(
        self,
        script_path: str,
        *,
        args: Optional[List[str]] = None,
        extra_env: Optional[Dict[str, str]] = None,
    ) -> ExecutionResult:
        """Execute a script and return the result."""
        pass
