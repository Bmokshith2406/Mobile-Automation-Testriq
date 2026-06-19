import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.domain import StepExecution
from app.services.ai import BaseAIProvider, get_ai_service


class MockAIProvider(BaseAIProvider):
    async def _generate(self, prompt: str) -> str:
        return "Mocked AI Response"

    async def generate_step_summary(self, step_intent: str, step_status: str, duration: float) -> str:
        return f"Mocked step summary for {step_intent}"

    async def generate_overall_description(
        self,
        total_steps: int,
        passed_steps: int,
        failed_steps: int,
        duration_sec: float,
    ) -> str:
        return f"Mocked overall summary for {total_steps} steps."

    async def enrich_steps_with_summaries(self, steps: list[StepExecution]) -> dict:
        for step in steps:
            step.ai_summary = f"Mocked AI for step {step.summary.step_index}"
        return {str(step.summary.step_index): step.ai_summary for step in steps}


@pytest.fixture
def mock_ai_service():
    return MockAIProvider()


@pytest.fixture
def app_client(mock_ai_service):
    from app.main import verify_api_key

    app.dependency_overrides[get_ai_service] = lambda: mock_ai_service
    app.dependency_overrides[verify_api_key] = lambda: True
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def _build_current_format_zip(*, include_video: bool = True, include_script: bool = True, malicious: bool = False) -> bytes:
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        zip_file.writestr("started_at.txt", "2026-06-02T10:00:00Z")
        zip_file.writestr("finished_at.txt", "2026-06-02T10:01:00Z")
        zip_file.writestr(
            "success/summary.json",
            json.dumps(
                {
                    "test_case_id": "<img src=x onerror=alert(1)>" if malicious else "TC_PARABANK_END_TO_END_001",
                    "run_id": "20260301_125049",
                    "status": "passed",
                }
            ),
        )

        if include_script:
            script_body = "<script>alert(1)</script>" if malicious else "test_case_id='TC-123'\nprint('hello')"
            zip_file.writestr("final_script.py", script_body)

        if include_video:
            zip_file.writestr("success/video/fakehash123.webm", b"fake_video_data")

        for i in range(3):
            folder_name = f"success/{i}__step_{i}_hash"
            zip_file.writestr(
                f"{folder_name}/step_summary.json",
                json.dumps(
                    {
                        "step_index": i,
                        "step_name": f"Step {i}",
                        "intent": "<script>alert(2)</script>" if malicious and i == 0 else f"Do {i}",
                        "status": "passed",
                        "duration_sec": 1.5,
                        "attempts": 1,
                        "max_retries": 3,
                        "started_at": "2026-06-02T10:00:05Z",
                        "url": "javascript:alert(3)" if malicious and i == 0 else "https://example.com",
                    }
                ),
            )
            zip_file.writestr(f"{folder_name}/screenshot.png", b"fake_png_bytes")

        zip_file.writestr(
            "repair_report.json",
            json.dumps(
                {
                    "final_status": "passed",
                    "iterations": 1,
                    "repairs": [{"attempt": 1, "outcome": "patched", "step_id": "0__step_0_hash"}],
                }
            ),
        )

    return zip_buffer.getvalue()


def _build_legacy_format_zip() -> bytes:
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        zip_file.writestr(
            "report.json",
            json.dumps(
                {
                    "name": "Legacy Login Flow",
                    "started_at": "2026-06-02T10:00:00Z",
                    "finished_at": "2026-06-02T10:01:00Z",
                }
            ),
        )
        zip_file.writestr("final_script.py", "test_case_id='LEGACY-123'\nprint('legacy')")
        zip_file.writestr("execution_video.mp4", b"legacy_video")
        zip_file.writestr(
            "steps/step-1/summary.json",
            json.dumps(
                {
                    "step_index": 1,
                    "step_name": "Open Login",
                    "intent": "Open the login page",
                    "status": "passed",
                    "duration_sec": 2.1,
                    "attempts": 1,
                    "max_retries": 1,
                    "execution_timestamp": 1717329600,
                    "url": "https://legacy.example.com/login",
                }
            ),
        )
        zip_file.writestr("steps/step-1/screenshot.jpeg", b"\xff\xd8fake_jpeg")
    return zip_buffer.getvalue()


@pytest.fixture
def valid_zip_bytes() -> bytes:
    return _build_current_format_zip()


@pytest.fixture
def malicious_zip_bytes() -> bytes:
    return _build_current_format_zip(malicious=True)


@pytest.fixture
def missing_artifacts_zip_bytes() -> bytes:
    return _build_current_format_zip(include_script=False)


@pytest.fixture
def no_video_zip_bytes() -> bytes:
    return _build_current_format_zip(include_video=False)


@pytest.fixture
def legacy_zip_bytes() -> bytes:
    return _build_legacy_format_zip()


@pytest.fixture
def sample_zip_path() -> Path:
    return Path("sample.zip")
