import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import pytest

from app.core.errors import APIException
from app.services.zip_service import ZipService


@dataclass
class MockUploadFile:
    file: BinaryIO
    filename: str = "test.zip"
    content_type: str = "application/zip"
    size: int = 1000


def test_extract_and_parse_current_format_success(valid_zip_bytes: bytes):
    service = ZipService()
    mock_file = MockUploadFile(file=io.BytesIO(valid_zip_bytes))

    result = service.extract_and_parse(mock_file)

    assert result.metadata.started_at == "2026-06-02T10:00:00Z"
    assert result.metadata.source_format == "current"
    assert len(result.steps) == 3

    step0 = result.steps[0]
    assert step0.summary.step_index == 0
    assert step0.summary.step_name == "Step 0"
    assert step0.screenshot is not None
    assert step0.screenshot.media_type == "image/png"

    assert result.artifacts.execution_video is not None
    assert result.artifacts.execution_video.media_type == "video/webm"
    assert result.artifacts.execution_video.data == b"fake_video_data"
    assert "TC-123" in result.artifacts.final_script


def test_extract_and_parse_legacy_format_success(legacy_zip_bytes: bytes):
    service = ZipService()
    mock_file = MockUploadFile(file=io.BytesIO(legacy_zip_bytes), filename="legacy.zip")

    result = service.extract_and_parse(mock_file)

    assert result.metadata.testcase_name == "Legacy Login Flow"
    assert result.metadata.source_format == "legacy"
    assert len(result.steps) == 1
    assert result.steps[0].summary.step_index == 1
    assert result.steps[0].screenshot is not None
    assert result.steps[0].screenshot.media_type == "image/jpeg"
    assert result.artifacts.execution_video is not None
    assert result.artifacts.execution_video.media_type == "video/mp4"


def test_extract_and_parse_missing_required_artifacts_fails(missing_artifacts_zip_bytes: bytes):
    service = ZipService()
    mock_file = MockUploadFile(file=io.BytesIO(missing_artifacts_zip_bytes), filename="broken.zip")

    with pytest.raises(APIException) as exc_info:
        service.extract_and_parse(mock_file)

    assert exc_info.value.status_code == 400
    assert "Missing required artifact" in exc_info.value.message


def test_extract_and_parse_device_scoped_appium_failure():
    zip_buffer = io.BytesIO()
    step_name = "0_iphone_latest__step_0_abc123_iphone_latest"
    attempt_prefix = f"failures/iphone_latest/{step_name}/attempt_1"
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        zip_file.writestr("started_at.txt", "2026-06-16T10:00:00Z")
        zip_file.writestr("finished_at.txt", "2026-06-16T10:02:00Z")
        zip_file.writestr("final_script.py", "print('appium matrix')")
        zip_file.writestr(
            "failures/summary.json",
            json.dumps(
                {
                    "test_case_id": "APPIUM_MATRIX",
                    "status": "failed",
                    "failed_step_index": 0,
                    "failed_device_slug": "iphone_latest",
                    "steps": [
                        {
                            "step_index": 0,
                            "step_name": step_name,
                            "status": "failed",
                            "duration_total_sec": 1.2,
                            "attempts": 1,
                            "max_retries": 1,
                            "device_label": "iPhone Latest",
                        }
                    ],
                }
            ),
        )
        zip_file.writestr(f"{attempt_prefix}/intent.txt", "Tap Login")
        zip_file.writestr(f"{attempt_prefix}/error.txt", "NoSuchElementException")
        zip_file.writestr(f"{attempt_prefix}/step_code.py", "element.click()")
        zip_file.writestr(f"{attempt_prefix}/screenshot.png", b"fake_png")
        zip_file.writestr(
            f"{attempt_prefix}/device_context.json",
            json.dumps({"label": "iPhone Latest", "slug": "iphone_latest"}),
        )

    service = ZipService()
    mock_file = MockUploadFile(file=io.BytesIO(zip_buffer.getvalue()), filename="appium.zip")

    result = service.extract_and_parse(mock_file)

    assert result.metadata.testcase_name == "APPIUM_MATRIX"
    assert len(result.steps) == 1
    assert result.steps[0].summary.status == "failed"
    assert result.steps[0].summary.step_name == step_name
    assert result.steps[0].screenshot is not None
    assert result.steps[0].source_path == f"{attempt_prefix}/step_code.py"


def test_extract_and_parse_appium_matrix_bundle_with_separate_run_dirs():
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        zip_file.writestr(
            "matrix_summary.json",
            json.dumps(
                {
                    "run_id": "matrix_abc123",
                    "status": "failed",
                    "kind": "appium_device_matrix",
                    "runs": [
                        {
                            "folder": "pixel_7",
                            "run_id": "run_pixel",
                            "status": "passed",
                            "device": {"label": "Pixel 7", "slug": "pixel_7"},
                        },
                        {
                            "folder": "iphone_latest",
                            "run_id": "run_iphone",
                            "status": "failed",
                            "device": {"label": "iPhone Latest", "slug": "iphone_latest"},
                        },
                    ],
                }
            ),
        )
        zip_file.writestr("pixel_7/started_at.txt", "2026-06-17T10:00:00Z")
        zip_file.writestr("pixel_7/finished_at.txt", "2026-06-17T10:01:00Z")
        zip_file.writestr("pixel_7/final_script.py", "print('pixel')")
        zip_file.writestr(
            "pixel_7/success/summary.json",
            json.dumps(
                {
                    "test_case_id": "APPIUM_MATRIX",
                    "status": "passed",
                    "device": {"label": "Pixel 7"},
                    "steps": [
                        {
                            "step_index": 0,
                            "step_name": "0__step_0_login",
                            "status": "passed",
                            "duration_total_sec": 1.0,
                            "attempts": 1,
                            "max_retries": 1,
                        }
                    ],
                }
            ),
        )
        zip_file.writestr(
            "pixel_7/success/0__step_0_login/step_summary.json",
            json.dumps(
                {
                    "step_index": 0,
                    "step_name": "0__step_0_login",
                    "intent": "Tap Login",
                    "status": "passed",
                    "duration_sec": 1.0,
                    "attempts": 1,
                    "max_retries": 1,
                }
            ),
        )
        zip_file.writestr("pixel_7/success/0__step_0_login/screenshot.png", b"pixel_png")

        step_name = "0__step_0_login"
        attempt_prefix = f"iphone_latest/failures/{step_name}/attempt_1"
        zip_file.writestr("iphone_latest/final_script.py", "print('iphone')")
        zip_file.writestr(
            "iphone_latest/failures/summary.json",
            json.dumps(
                {
                    "test_case_id": "APPIUM_MATRIX",
                    "status": "failed",
                    "device": {"label": "iPhone Latest"},
                    "steps": [
                        {
                            "step_index": 0,
                            "step_name": step_name,
                            "status": "failed",
                            "duration_total_sec": 2.0,
                            "attempts": 1,
                            "max_retries": 1,
                        }
                    ],
                }
            ),
        )
        zip_file.writestr(f"{attempt_prefix}/intent.txt", "Tap Login")
        zip_file.writestr(f"{attempt_prefix}/error.txt", "NoSuchElementException")
        zip_file.writestr(f"{attempt_prefix}/step_code.py", "element.click()")
        zip_file.writestr(f"{attempt_prefix}/screenshot.png", b"iphone_png")

    service = ZipService()
    mock_file = MockUploadFile(file=io.BytesIO(zip_buffer.getvalue()), filename="matrix.zip")

    result = service.extract_and_parse(mock_file)

    assert result.metadata.source_format == "appium_matrix"
    assert result.metadata.testcase_name == "APPIUM_MATRIX"
    assert len(result.steps) == 2
    assert result.steps[0].summary.step_name == "Pixel 7 / 0__step_0_login"
    assert result.steps[1].summary.step_name == "iPhone Latest / 0__step_0_login"
    assert result.steps[1].summary.status == "failed"
    assert result.steps[1].source_path == f"{attempt_prefix}/step_code.py"
    assert "print('pixel')" in result.artifacts.final_script
    assert "print('iphone')" in result.artifacts.final_script


def test_extract_and_parse_real_sample_zip(sample_zip_path: Path):
    service = ZipService()
    with sample_zip_path.open("rb") as handle:
        mock_file = MockUploadFile(
            file=handle,
            filename=sample_zip_path.name,
            size=sample_zip_path.stat().st_size,
        )
        result = service.extract_and_parse(mock_file)

    assert result.metadata.testcase_name == "TC_PARABANK_END_TO_END_001"
    assert result.metadata.source_format == "current"
    assert len(result.steps) == 17
    assert result.artifacts.execution_video is not None
    assert result.artifacts.execution_video.media_type == "video/webm"
