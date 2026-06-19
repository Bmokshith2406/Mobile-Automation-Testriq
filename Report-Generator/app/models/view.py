from typing import Optional

from pydantic import BaseModel


class ReportStepView(BaseModel):
    step_id: str
    index: int
    name: str
    status: str
    intent: str
    duration: float
    attempts: int
    max_retries: int
    url: str
    ai_summary: str
    screenshot_data: str = ""
    screenshot_media_type: str = ""
    timestamp: str = "N/A"


class ReportArtifactsView(BaseModel):
    execution_video_data: str = ""
    execution_video_media_type: str = ""
    final_script: str = ""
    final_script_filename: str = "final_script.py"
    repair_report: Optional[dict] = None


class ReportViewModel(BaseModel):
    testcase_name: str
    generated_at: str
    started_at: str = "N/A"
    finished_at: str = "N/A"
    overall_description: str = ""
    total_steps: int
    passed_steps: int
    failed_steps: int
    total_duration: float
    success_rate: float
    source_format: str
    steps: list[ReportStepView]
    artifacts: ReportArtifactsView
    final_failure_explanation: Optional[dict] = None
