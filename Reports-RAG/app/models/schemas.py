from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class BaseSchema(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",
    )


class ReportUploadResponse(BaseSchema):
    status: str = Field(default="success")
    message: str = Field(default="Report uploaded successfully")
    report_id: str
    name: str
    created_at: datetime


class ReportDownloadResponse(BaseSchema):
    id: str
    name: str
    html_content: str
    created_at: datetime
    updated_at: datetime
    size: int


class ReportMetadata(BaseSchema):
    id: str = Field(alias="_id")
    name: str
    filename: Optional[str] = None
    content_type: str
    created_at: datetime
    updated_at: datetime
    size: int


class ReportListResponse(BaseSchema):
    success: bool = True
    count: int
    skip: int
    limit: int
    reports: List[ReportMetadata]


class ReportDeleteResponse(BaseSchema):
    success: bool = True
    report_id: str
    message: str = "Report deleted successfully"


class ReportDeleteAllResponse(BaseSchema):
    success: bool = True
    deleted_reports: int
    message: str = "All reports deleted successfully"


class HealthResponse(BaseSchema):
    status: str
    service: Optional[str] = None
    version: Optional[str] = None
    uptime_seconds: Optional[float] = None
    db: Optional[str] = None
    metrics: Optional[Dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
