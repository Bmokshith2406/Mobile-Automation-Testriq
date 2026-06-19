from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


StepStatus = Literal["passed", "failed", "skipped", "broken", "unknown"]


class ArtifactBinary(BaseModel):
    filename: str
    media_type: str
    data: bytes
    size_bytes: int = Field(ge=0)


class StepSummary(BaseModel):
    step_index: int = Field(ge=0)
    step_name: str = ""
    intent: str = ""
    status: StepStatus = "unknown"
    duration_sec: float = Field(default=0.0, ge=0.0)
    attempts: int = Field(default=0, ge=0)
    max_retries: int = Field(default=0, ge=0)
    url: str = ""

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value: Any) -> str:
        if value is None:
            return "unknown"
        normalized = str(value).strip().lower()
        return normalized if normalized in {"passed", "failed", "skipped", "broken"} else "unknown"


class StepExecution(BaseModel):
    summary: StepSummary
    screenshot: Optional[ArtifactBinary] = None
    execution_timestamp: Optional[Any] = None
    ai_summary: str = ""
    source_path: str = ""


class Artifacts(BaseModel):
    execution_video: Optional[ArtifactBinary] = None
    final_script: str = ""
    final_script_filename: str = ""
    repair_report: Optional[dict] = None


class ReportMetadata(BaseModel):
    testcase_name: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    overall_description: str = ""
    source_format: str = "unknown"


class ReportData(BaseModel):
    metadata: ReportMetadata
    steps: list[StepExecution]
    artifacts: Artifacts
    final_failure_explanation: Optional[dict] = None
