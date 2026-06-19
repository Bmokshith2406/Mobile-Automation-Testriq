from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.services.pipeline_service import PipelineService


client = TestClient(app)


def sample_pipeline_response(**overrides):
    payload = {
        "status": "success",
        "routing_path": "existing_script",
        "matched_probability": 100.0,
        "canonical_testcase_id": "test_tc_123",
        "testcase_id": "test_tc_123",
        "report_id": "report_111",
        "executor_status": "passed",
        "executor_run_id": "run_111",
        "executor_duration": "1250",
        "executor_artifact_kind": "single_run",
        "executor_matrix_run_count": None,
        "executor_failed_step_index": None,
        "testcase_rag_status": "not_required",
        "methods_rag_status": "not_required",
        "duration": 1.25,
    }
    payload.update(overrides)
    return payload


def test_run_pipeline_by_id_prefers_structured_testcase_snapshot():
    mock_doc = {
        "Test Case ID": "test_tc_123",
        "Test Case Description": "Verify world clock screen",
        "Feature": "Clock",
        "Platform": "appium",
        "playwright_script_id": "script_xyz_456",
        "structured_test_case": {
            "test_case_id": "test_tc_123",
            "description": "Verify world clock screen",
            "feature": "Clock",
            "target_framework": "appium",
            "appium_config": {
                "platformName": "Android",
                "devices": [
                    {
                        "label": "Pixel 7",
                        "deviceName": "Pixel 7",
                        "appPackage": "com.google.android.deskclock",
                        "appActivity": "com.android.deskclock.DeskClock",
                    }
                ],
            },
            "appium_server_url": "http://127.0.0.1:4723/wd/hub",
            "steps": [
                {
                    "step_id": "STEP_01",
                    "description": "Open World Clock",
                    "expected_outcome": "World Clock is visible",
                    "matched_script": {
                        "language": "python",
                        "framework": "appium",
                        "raw_code": "driver.find_element(...)",
                    },
                }
            ],
        },
    }

    with patch.object(
        PipelineService,
        "get_testcase_with_history",
        AsyncMock(return_value={"testcase": mock_doc, "execution_history": []}),
    ):
        with patch.object(
            PipelineService,
            "execute_run",
            AsyncMock(return_value=sample_pipeline_response(executor_artifact_kind="appium_device_matrix")),
        ) as mock_execute:
            response = client.post("/testcase/test_tc_123/run")

    assert response.status_code == 200
    res_data = response.json()
    assert res_data["status"] == "success"
    assert res_data["executor_artifact_kind"] == "appium_device_matrix"

    mock_execute.assert_called_once()
    called_args = mock_execute.call_args.kwargs
    payload = called_args["testcase_payload"]

    assert payload["test_case_id"] == "test_tc_123"
    assert payload["description"] == "Verify world clock screen"
    assert payload["feature"] == "Clock"
    assert payload["target_framework"] == "appium"
    assert payload["appium_config"]["devices"][0]["deviceName"] == "Pixel 7"
    assert payload["appium_server_url"] == "http://127.0.0.1:4723/wd/hub"
    assert payload["steps"][0]["matched_script"]["framework"] == "appium"
    assert called_args["script_id"] == "script_xyz_456"


def test_run_pipeline_by_id_falls_back_to_legacy_flattened_fields():
    mock_doc = {
        "Test Case ID": "legacy_tc_001",
        "Test Case Description": "Verify system login",
        "Feature": "Auth",
        "Platform": "unsupported-framework",
        "Pre-requisites": "- Server running\n- User created",
        "Steps": "Step 1: Enter password -> Expected: Text matches\n\nStep 2: Submit form -> Expected: Logged in",
        "script_id": "script_xyz_456",
    }

    with patch.object(
        PipelineService,
        "get_testcase_with_history",
        AsyncMock(return_value={"testcase": mock_doc, "execution_history": []}),
    ):
        with patch.object(
            PipelineService,
            "execute_run",
            AsyncMock(return_value=sample_pipeline_response(canonical_testcase_id="legacy_tc_001", testcase_id="legacy_tc_001")),
        ) as mock_execute:
            response = client.post("/testcase/legacy_tc_001/run")

    assert response.status_code == 200
    assert response.json()["report_id"] == "report_111"

    mock_execute.assert_called_once()
    called_args = mock_execute.call_args.kwargs
    payload = called_args["testcase_payload"]

    assert payload["test_case_id"] == "legacy_tc_001"
    assert payload["description"] == "Verify system login"
    assert payload["feature"] == "Auth"
    assert payload["target_framework"] == "playwright"
    assert len(payload["prerequisites"]) == 2
    assert payload["prerequisites"][0]["prerequisite_id"] == "prereq_1"
    assert payload["prerequisites"][0]["description"] == "Server running"
    assert len(payload["steps"]) == 2
    assert payload["steps"][0]["step_id"] == "step_1"
    assert payload["steps"][0]["description"] == "Enter password"
    assert payload["steps"][0]["expected_outcome"] == "Text matches"
    assert called_args["script_id"] == "script_xyz_456"


def test_run_pipeline_by_id_not_found():
    with patch.object(
        PipelineService,
        "get_testcase_with_history",
        AsyncMock(return_value={"testcase": None}),
    ):
        response = client.post("/testcase/nonexistent_id/run")

    assert response.status_code == 404
    assert "Test case not found" in response.json()["detail"]
