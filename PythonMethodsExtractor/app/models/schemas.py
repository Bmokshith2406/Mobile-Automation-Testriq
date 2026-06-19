from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


def utc_timestamp() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


# -----------------------------------------
# API LOG MODEL
# -----------------------------------------
class APILog(BaseModel):
    timestamp: datetime = Field(default_factory=utc_timestamp)
    method: Optional[str] = None
    path: Optional[str] = None
    query_params: Optional[Dict[str, Any]] = None
    ip: Optional[str] = None
    user_agent: Optional[str] = None
    request_id: Optional[str] = None
    correlation_id: Optional[str] = None
    trace_id: Optional[str] = None
    duration_ms: Optional[float] = None
    status: Optional[int] = None
    file_name: Optional[str] = None
    method_count: Optional[int] = None
    chunk_count: Optional[int] = None
    python_file_count: Optional[int] = None
    total_file_count: Optional[int] = None
    skipped_file_count: Optional[int] = None
    source_type: Optional[str] = None
    storage_requested: Optional[bool] = None
    storage_error: Optional[str] = None
    error: Optional[str] = None
    traceback: Optional[str] = None

    model_config = {
        "from_attributes": False
    }


# -----------------------------------------
# RAW SCRIPT STORAGE MODEL
# -----------------------------------------
class RawScript(BaseModel):
    filename: str
    content: str
    size: int
    source_type: Optional[str] = None
    script_sha256: Optional[str] = None
    timestamp: datetime = Field(default_factory=utc_timestamp)

    model_config = {
        "from_attributes": False
    }
