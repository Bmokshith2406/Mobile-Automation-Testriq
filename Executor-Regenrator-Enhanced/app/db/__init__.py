"""
Compatibility exports for legacy database imports.
"""

from app.core.database import DatabaseManager, get_database, get_repository, transaction
from app.models.database import ExecutionRecord, FailurePattern, RepairRecord

__all__ = [
    "DatabaseManager",
    "get_database",
    "get_repository",
    "transaction",
    "RepairRecord",
    "ExecutionRecord",
    "FailurePattern",
]
