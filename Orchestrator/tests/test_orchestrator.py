import asyncio
import csv
import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import PipelineRunRequest, TestCase as OrchestratorTestCase
from app.services import pipeline_service
from app.services.pipeline_service import PipelineService


class NullLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


class FakeResponse:
    def __init__(self, status_code, payload=None, text="", content=b"", headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.content = content or text.encode("utf-8")
        self.headers = headers or {}

    def json(self):
        return self._payload

    async def aread(self):
        return self.content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def sample_testcase_payload():
    return {
        "test_case_id": "TC_ORANGEHRM_LOGIN_001",
        "description": "OrangeHRM login happy path flow using strictly atomic steps.",
        "target_framework": "playwright",
        "steps": [
            {
                "step_id": "STEP_01",
                "description": "Navigate to OrangeHRM login page.",
                "expected_outcome": "OrangeHRM login page should load.",
            }
        ],
    }


def sample_appium_testcase_payload():
    return {
        "test_case_id": "APPIUM_CLOCK_ALARM_WORLD_TIMER_025",
        "description": "Verify the world clock screen opens on Android.",
        "target_framework": "appium",
        "appium_config": {
            "platformName": "Android",
            "automationName": "UiAutomator2",
            "devices": [
                {
                    "label": "Pixel 7",
                    "deviceName": "Pixel 7",
                    "appPackage": "com.google.android.deskclock",
                    "appActivity": "com.android.deskclock.DeskClock",
                }
            ],
        },
        "steps": [
            {
                "step_id": "STEP_01",
                "description": "Open the Clock app and navigate to World Clock.",
                "expected_outcome": "The World Clock screen is visible.",
            }
        ],
    }


def sample_pipeline_response(**overrides):
    payload = {
        "status": "success",
        "routing_path": "new_generated",
        "matched_probability": None,
        "canonical_testcase_id": "tc-canonical",
        "testcase_id": "tc-canonical",
        "report_id": "report-1",
        "executor_status": "passed",
        "executor_run_id": "run-1",
        "executor_duration": "12",
        "executor_artifact_kind": "single_run",
        "executor_matrix_run_count": None,
        "executor_failed_step_index": None,
        "testcase_rag_status": "ingested",
        "methods_rag_status": "uploaded",
        "duration": 1.25,
    }
    payload.update(overrides)
    return payload


def write_executor_zip(zip_path):
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "final_script.py",
            "async def _step_0_abcdef123456(page):\n    await page.click('text=Login')\n",
        )


def write_matrix_executor_zip(zip_path):
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "matrix_summary.json",
            json.dumps(
                {
                    "kind": "appium_device_matrix",
                    "runs": [
                        {"device_label": "Pixel 7", "status": "passed"},
                        {"device_label": "Pixel Tablet", "status": "failed"},
                    ],
                }
            ),
        )
        archive.writestr(
            "execution_manifest.json",
            json.dumps({"failed_step_index": 3}),
        )
        archive.writestr(
            "devices/pixel-7/final_script.py",
            "print('device-specific final script')\n",
        )


def test_orchestrator_run_validation():
    client = TestClient(app)
    response = client.post("/run", json={"description": "bad payload"})
    assert response.status_code == 422


def test_run_accepts_valid_appium_payload_with_appium_config(monkeypatch):
    async def fake_execute_run(testcase_payload, request_id, script_id=None):
        assert testcase_payload["target_framework"] == "appium"
        assert testcase_payload["appium_config"]["devices"][0]["device_name"] == "Pixel 7"
        assert script_id is None
        assert request_id == "req-appium"
        return sample_pipeline_response(
            routing_path="new_generated",
            executor_artifact_kind="appium_device_matrix",
            executor_matrix_run_count=1,
        )

    monkeypatch.setattr(PipelineService, "execute_run", staticmethod(fake_execute_run))
    client = TestClient(app)

    response = client.post(
        "/run",
        json=sample_appium_testcase_payload(),
        headers={"X-Request-ID": "req-appium"},
    )

    assert response.status_code == 200
    assert response.json()["executor_artifact_kind"] == "appium_device_matrix"
    assert response.json()["executor_matrix_run_count"] == 1


def test_run_accepts_wrapped_generator_style_payload(monkeypatch):
    async def fake_execute_run(testcase_payload, request_id, script_id=None):
        assert testcase_payload["test_case_id"] == "TC_ORANGEHRM_LOGIN_001"
        assert testcase_payload["webhook_url"] == "https://hooks.example.test/orchestrator"
        assert request_id == "req-wrapped"
        assert script_id is None
        return sample_pipeline_response()

    monkeypatch.setattr(PipelineService, "execute_run", staticmethod(fake_execute_run))
    client = TestClient(app)

    response = client.post(
        "/run",
        json={
            "test_case": sample_testcase_payload(),
            "webhook_url": "https://hooks.example.test/orchestrator",
        },
        headers={"X-Request-ID": "req-wrapped"},
    )

    assert response.status_code == 200
    assert response.json()["routing_path"] == "new_generated"


def test_run_rejects_appium_config_for_non_appium_framework():
    client = TestClient(app)
    payload = sample_testcase_payload()
    payload["appium_config"] = sample_appium_testcase_payload()["appium_config"]

    response = client.post("/run", json=payload)

    assert response.status_code == 422
    assert "appium_config" in response.text


def test_run_rejects_generator_incompatible_request_models():
    client = TestClient(app)

    duplicate_steps = sample_testcase_payload()
    duplicate_steps["steps"].append(
        {
            "step_id": "STEP_01",
            "description": "Duplicate step id.",
            "expected_outcome": "Should be rejected.",
        }
    )
    assert client.post("/run", json=duplicate_steps).status_code == 422

    invalid_id = sample_testcase_payload()
    invalid_id["test_case_id"] = "TC LOGIN 001"
    assert client.post("/run", json=invalid_id).status_code == 422

    invalid_script = sample_testcase_payload()
    invalid_script["steps"][0]["matched_script"] = {
        "language": "ruby",
        "framework": "playwright",
        "raw_code": "await page.click('text=Login')",
    }
    assert client.post("/run", json=invalid_script).status_code == 422

    extra_field = sample_testcase_payload()
    extra_field["steps"][0]["unexpected"] = "nope"
    assert client.post("/run", json=extra_field).status_code == 422


def test_only_post_run_is_public_execution_endpoint(monkeypatch):
    async def fake_execute_run(testcase_payload, request_id, script_id=None):
        assert testcase_payload["test_case_id"] == "TC_ORANGEHRM_LOGIN_001"
        assert request_id == "req-route"
        assert script_id is None
        return sample_pipeline_response()

    monkeypatch.setattr(PipelineService, "execute_run", staticmethod(fake_execute_run))
    client = TestClient(app)

    response = client.post("/run", json=sample_testcase_payload(), headers={"X-Request-ID": "req-route"})
    assert response.status_code == 200
    assert response.json()["routing_path"] == "new_generated"

    assert client.post("/run/direct", json=sample_testcase_payload()).status_code == 404
    assert client.post("/run/TC_ORANGEHRM_LOGIN_001", json=sample_testcase_payload()).status_code == 404


def test_search_uses_normal_key_and_strict_85_threshold(monkeypatch):
    captured = []
    probabilities = [85.0, 85.1]

    class FakeClient:
        async def post(self, url, headers, json, timeout):
            captured.append({"url": url, "headers": headers, "json": json})
            return FakeResponse(200, {"results": [{"id": "tc-match", "probability": probabilities.pop(0)}]})

    async def fake_get_client():
        return FakeClient()

    monkeypatch.setattr(pipeline_service, "get_client", fake_get_client)
    monkeypatch.setattr(pipeline_service.settings, "TESTCASES_RAG_API_KEY", "normal-key")
    monkeypatch.setattr(pipeline_service.settings, "TESTCASES_RAG_URL", "http://testcases-rag")

    assert asyncio.run(PipelineService._search_existing_testcase(sample_testcase_payload(), NullLogger())) is None
    matched = asyncio.run(PipelineService._search_existing_testcase(sample_testcase_payload(), NullLogger()))

    assert matched["id"] == "tc-match"
    assert captured[-1]["headers"]["X-API-Key"] == "normal-key"
    assert "X-Admin-API-Key" not in captured[-1]["headers"]


def test_fetch_script_uses_admin_key(monkeypatch):
    captured = []

    class FakeClient:
        async def get(self, url, headers, timeout):
            captured.append({"url": url, "headers": headers})
            return FakeResponse(200, {"code": "print('stored')"})

    async def fake_get_client():
        return FakeClient()

    monkeypatch.setattr(pipeline_service, "get_client", fake_get_client)
    monkeypatch.setattr(pipeline_service.settings, "TESTCASES_RAG_URL", "http://testcases-rag")
    monkeypatch.setattr(pipeline_service.settings, "TESTCASES_RAG_ADMIN_API_KEY", "admin-key")

    script = asyncio.run(PipelineService._fetch_script("script-1"))

    assert script == "print('stored')"
    assert captured[0]["url"] == "http://testcases-rag/api/get-script/script-1"
    assert captured[0]["headers"] == {"X-Admin-API-Key": "admin-key"}


def test_generator_payload_strips_orchestrator_only_fields_and_matches_generator_model():
    payload = sample_testcase_payload()
    payload["_id"] = "internal-id"
    payload["feature"] = "Login"
    payload["webhook_url"] = "https://hooks.example.test/generator"
    payload["appium_server_url"] = "http://127.0.0.1:4723"
    payload["steps"][0]["matched_script"] = {
        "language": "python",
        "framework": "playwright",
        "raw_code": "await page.goto('https://example.test')",
    }

    shaped = PipelineService.build_generator_payload(payload)

    assert "_id" not in shaped
    assert "feature" not in shaped
    assert "webhook_url" not in shaped
    assert "appium_server_url" not in shaped
    assert shaped == {
        "test_case_id": "TC_ORANGEHRM_LOGIN_001",
        "description": "OrangeHRM login happy path flow using strictly atomic steps.",
        "target_framework": "playwright",
        "prerequisites": [],
        "steps": [
            {
                "step_id": "STEP_01",
                "description": "Navigate to OrangeHRM login page.",
                "expected_outcome": "OrangeHRM login page should load.",
                "matched_script": {
                    "language": "python",
                    "framework": "playwright",
                    "raw_code": "await page.goto('https://example.test')",
                },
            }
        ],
    }


def test_generator_request_wraps_test_case_and_forwards_webhook_only_at_top_level(monkeypatch):
    monkeypatch.setattr(pipeline_service.settings, "GENERATOR_URL", "http://generator")
    monkeypatch.setattr(pipeline_service.settings, "GENERATOR_API_KEY", "generator-key")

    payload = OrchestratorTestCase.model_validate(sample_appium_testcase_payload()).model_dump()
    payload["webhook_url"] = "https://hooks.example.test/generator"
    payload["feature"] = "Clock"
    payload["_id"] = "internal-id"
    payload["appium_server_url"] = "http://127.0.0.1:4723/wd/hub"

    request_spec = PipelineService.build_generator_request(payload, "req-1")

    assert request_spec["url"] == "http://generator/generate/"
    assert request_spec["headers"]["X-API-Key"] == "generator-key"
    assert request_spec["headers"]["Content-Type"] == "application/json"
    assert request_spec["json"]["webhook_url"] == "https://hooks.example.test/generator"
    assert "webhook_url" not in request_spec["json"]["test_case"]
    assert "feature" not in request_spec["json"]["test_case"]
    assert "_id" not in request_spec["json"]["test_case"]
    assert request_spec["json"]["test_case"]["appium_config"]["devices"][0]["device_name"] == "Pixel 7"


def test_pipeline_run_request_accepts_wrapped_generator_payload_shape():
    request_model = PipelineRunRequest.model_validate(
        {
            "test_case": sample_appium_testcase_payload(),
            "webhook_url": "https://hooks.example.test/orchestrator",
            "appium_server_url": "http://127.0.0.1:4723/wd/hub",
        }
    )

    assert request_model.test_case.test_case_id == "APPIUM_CLOCK_ALARM_WORLD_TIMER_025"
    assert request_model.test_case.webhook_url == "https://hooks.example.test/orchestrator"
    assert request_model.test_case.appium_server_url == "http://127.0.0.1:4723/wd/hub"


def test_generator_request_validates_against_real_generate_request_model(monkeypatch):
    monkeypatch.setattr(pipeline_service.settings, "GENERATOR_URL", "http://generator")
    monkeypatch.setattr(pipeline_service.settings, "GENERATOR_API_KEY", "generator-key")

    request_spec = PipelineService.build_generator_request(
        {
            **OrchestratorTestCase.model_validate(sample_appium_testcase_payload()).model_dump(),
            "webhook_url": "https://hooks.example.test/generator",
        },
        "req-contract",
    )

    generator_root = Path(__file__).resolve().parents[2] / "Automation-Script-Generator"
    validator = (
        "import json, sys\n"
        "from app.routes.generate import GenerateRequest\n"
        "GenerateRequest.model_validate(json.loads(sys.stdin.read()))\n"
        "print('ok')\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(generator_root)

    proc = subprocess.run(
        [sys.executable, "-c", validator],
        input=json.dumps(request_spec["json"]),
        capture_output=True,
        text=True,
        cwd=generator_root,
        env=env,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().endswith("ok")


def test_downstream_request_builders_lock_exact_junction_contracts(monkeypatch):
    monkeypatch.setattr(pipeline_service.settings, "GENERATOR_URL", "http://generator")
    monkeypatch.setattr(pipeline_service.settings, "GENERATOR_API_KEY", "generator-key")
    monkeypatch.setattr(pipeline_service.settings, "EXECUTOR_URL", "http://executor")
    monkeypatch.setattr(pipeline_service.settings, "EXECUTOR_API_KEY", "executor-key")
    monkeypatch.setattr(pipeline_service.settings, "REPORTER_URL", "http://reporter")
    monkeypatch.setattr(pipeline_service.settings, "REPORTER_API_KEY", "reporter-key")
    monkeypatch.setattr(pipeline_service.settings, "REPORTS_RAG_URL", "http://reports-rag")
    monkeypatch.setattr(pipeline_service.settings, "REPORTS_RAG_API_KEY", "reports-key")
    monkeypatch.setattr(pipeline_service.settings, "TESTCASES_RAG_URL", "http://testcases-rag")
    monkeypatch.setattr(pipeline_service.settings, "TESTCASES_RAG_API_KEY", "testcases-key")
    monkeypatch.setattr(pipeline_service.settings, "EXTRACTOR_URL", "http://extractor")
    monkeypatch.setattr(pipeline_service.settings, "EXTRACTOR_API_KEY", "extractor-key")
    monkeypatch.setattr(pipeline_service.settings, "METHODS_RAG_URL", "http://methods-rag")
    monkeypatch.setattr(pipeline_service.settings, "METHODS_RAG_API_KEY", "methods-key")

    generator = PipelineService.build_generator_request(
        dict(sample_testcase_payload(), feature="Login", webhook_url="https://hooks.example.test/generator"),
        "req-1",
    )
    assert generator["url"] == "http://generator/generate/"
    assert generator["headers"]["X-API-Key"] == "generator-key"
    assert generator["headers"]["Content-Type"] == "application/json"
    assert generator["json"]["webhook_url"] == "https://hooks.example.test/generator"
    assert "feature" not in generator["json"]["test_case"]

    search = PipelineService.build_testcases_search_request(dict(sample_testcase_payload(), feature="Login"))
    assert search["url"] == "http://testcases-rag/api/search"
    assert search["headers"] == {"X-API-Key": "testcases-key", "Content-Type": "application/json"}
    assert search["json"] == {
        "query": "OrangeHRM login happy path flow using strictly atomic steps.",
    }

    script_file = io.BytesIO(b"print('ok')")
    executor = PipelineService.build_executor_request(script_file, "req-1")
    assert executor["url"] == "http://executor/executor/playwright/run"
    assert executor["headers"] == {"X-API-Key": "executor-key", "X-Request-ID": "req-1"}
    assert executor["files"]["script"][0] == "generated_script.py"
    assert executor["files"]["script"][2] == "text/x-python"

    selenium_executor = PipelineService.build_framework_executor_request(
        io.BytesIO(b"print('ok')"),
        "req-1",
        framework="selenium",
        testcase_payload={},
    )
    assert selenium_executor["url"] == "http://executor/executor/selenium/run"

    cypress_executor = PipelineService.build_framework_executor_request(
        io.BytesIO(b"print('ok')"),
        "req-1",
        framework="cypress",
        testcase_payload={},
    )
    assert cypress_executor["url"] == "http://executor/executor/cypress/run"

    appium_executor = PipelineService.build_framework_executor_request(
        io.BytesIO(b"print('ok')"),
        "req-1",
        framework="appium",
        testcase_payload={
            "appium_server_url": "http://34.46.45.187:4723/wd/hub",
            "appium_device_filter": "Pixel 7",
            "appium_device_matrix": {"devices": [{"label": "Pixel 7"}]},
        },
    )
    assert appium_executor["url"] == "http://executor/executor/appium/run"
    assert appium_executor["data"]["appium_server_url"] == "http://34.46.45.187:4723/wd/hub"
    assert appium_executor["data"]["appium_device_filter"] == "Pixel 7"
    assert json.loads(appium_executor["data"]["appium_device_matrix"]) == {
        "devices": [{"label": "Pixel 7"}]
    }

    unknown_executor = PipelineService.build_framework_executor_request(
        io.BytesIO(b"print('ok')"),
        "req-1",
        framework=None,
        testcase_payload={},
    )
    assert unknown_executor["url"] == "http://executor/executor/playwright/run"

    zip_file = io.BytesIO(b"PK")
    reporter = PipelineService.build_report_generator_request(zip_file, "req-1")
    assert reporter["url"] == "http://reporter/api/v1/generate-report"
    assert reporter["headers"]["X-API-Key"] == "reporter-key"
    assert reporter["headers"]["Accept"] == "text/html"
    assert reporter["files"]["file"][0] == "execution_artifacts.zip"
    assert reporter["files"]["file"][2] == "application/zip"

    reports_upload = PipelineService.build_reports_rag_upload_request("<html>ok</html>", "Login Report", "req-1")
    assert reports_upload["url"] == "http://reports-rag/v1/api/reports/upload"
    assert reports_upload["headers"] == {"X-API-Key": "reports-key", "X-Request-ID": "req-1"}
    assert reports_upload["data"] == {"name": "Login Report"}
    assert reports_upload["files"]["file"] == ("report.html", b"<html>ok</html>", "text/html")

    ingest = PipelineService.build_testcases_ingest_request("print('final')", sample_testcase_payload(), "tc-1")
    assert ingest["url"] == "http://testcases-rag/api/testcases/ingest-full"
    assert ingest["headers"] == {"X-API-Key": "testcases-key"}
    assert ingest["files"]["file"] == ("final_script.py", b"print('final')", "text/x-python")
    normalized = json.loads(ingest["data"]["testcase_json"])
    assert normalized["_id"] == "tc-1"
    assert normalized["Test Case ID"] == "TC_ORANGEHRM_LOGIN_001"
    assert normalized["Platform"] == "playwright"
    assert normalized["script_framework"] == "playwright"
    assert normalized["script_language"] == "python"
    assert normalized["structured_test_case"]["target_framework"] == "playwright"

    sync = PipelineService.build_testcases_sync_request(
        "print('final')",
        "tc-1",
        testcase_payload=sample_testcase_payload(),
    )
    assert sync["url"] == "http://testcases-rag/api/testcases/tc-1/sync-script"
    assert sync["files"]["file"] == ("final_script.py", b"print('final')", "text/x-python")
    sync_normalized = json.loads(sync["data"]["testcase_json"])
    assert sync_normalized["_id"] == "tc-1"
    assert sync_normalized["script_framework"] == "playwright"
    assert sync_normalized["script_language"] == "python"
    assert sync_normalized["structured_test_case"]["steps"][0]["step_id"] == "STEP_01"

    extractor = PipelineService.build_extractor_request("print('final')")
    assert extractor["url"] == "http://extractor/extract/"
    assert extractor["headers"] == {"X-API-Key": "extractor-key"}
    assert extractor["data"] == {"include_method_name_pattern": pipeline_service.STEP_METHOD_PATTERN}
    assert extractor["files"]["file"] == ("final_script.py", b"print('final')", "text/x-python")

    methods_csv = "Raw Method\nasync def _step_0_abcdef123456(page):\n    pass\n".encode("utf-8")
    methods = PipelineService.build_methodsrag_upload_request(
        methods_csv,
        framework="playwright",
        language="python",
    )
    assert methods["url"] == "http://methods-rag/api/upload-methods"
    assert methods["headers"] == {"X-API-Key": "methods-key"}
    assert methods["data"] == {"framework": "playwright", "language": "python"}
    assert methods["files"]["file"] == ("methods.csv", methods_csv, "text/csv")
    csv_rows = list(csv.reader(io.StringIO(methods["files"]["file"][1].decode("utf-8"))))
    assert csv_rows[0] == ["Raw Method"]


def test_appium_executor_request_top_level_runtime_fields_override_derived_matrix():
    request_spec = PipelineService.build_framework_executor_request(
        io.BytesIO(b"print('ok')"),
        "req-1",
        framework="appium",
        testcase_payload={
            "appium_server_url": "http://explicit-server:4723/wd/hub",
            "appium_device_filter": "Pixel 8",
            "appium_device_matrix": {"devices": [{"label": "Explicit Device"}]},
            "appium_config": sample_appium_testcase_payload()["appium_config"],
        },
    )

    assert request_spec["data"]["appium_server_url"] == "http://explicit-server:4723/wd/hub"
    assert request_spec["data"]["appium_device_filter"] == "Pixel 8"
    assert json.loads(request_spec["data"]["appium_device_matrix"]) == {
        "devices": [{"label": "Explicit Device"}]
    }


def test_appium_executor_request_derives_matrix_from_appium_config_devices_when_missing():
    request_spec = PipelineService.build_framework_executor_request(
        io.BytesIO(b"print('ok')"),
        "req-1",
        framework="appium",
        testcase_payload=sample_appium_testcase_payload(),
    )

    assert "appium_server_url" not in request_spec["data"]
    assert "appium_device_filter" not in request_spec["data"]
    assert json.loads(request_spec["data"]["appium_device_matrix"]) == {
        "devices": sample_appium_testcase_payload()["appium_config"]["devices"]
    }


def test_matrix_artifacts_keep_generated_script_as_canonical_sync_source(tmp_path, monkeypatch):
    zip_path = tmp_path / "matrix_artifacts.zip"
    write_matrix_executor_zip(zip_path)
    captured = {}

    async def fake_sync_testcaserag(*, final_script_content, testcase_payload, canonical_testcase_id, mode, req_logger):
        captured["sync_script"] = final_script_content
        captured["sync_mode"] = mode
        return {
            "status": "synced",
            "canonical_testcase_id": canonical_testcase_id,
            "script_id": "script-1",
        }

    async def fake_extract_and_upload_methods(final_script_content, req_logger, *, framework=None, language=None):
        captured["methods_script"] = final_script_content
        captured["methods_framework"] = framework
        captured["methods_language"] = language
        return "uploaded"

    monkeypatch.setattr(PipelineService, "_sync_testcaserag", staticmethod(fake_sync_testcaserag))
    monkeypatch.setattr(PipelineService, "_extract_and_upload_methods", staticmethod(fake_extract_and_upload_methods))

    result = asyncio.run(
        PipelineService._persist_generated_artifacts(
            zip_path=zip_path,
            testcase_payload=sample_appium_testcase_payload(),
            canonical_testcase_id="tc-existing",
            mode="existing",
            generated_script_content="print('generated canonical appium script')\n",
            req_logger=NullLogger(),
        )
    )

    assert result["testcase_rag_status"] == "synced"
    assert captured["sync_mode"] == "existing"
    assert captured["sync_script"] == "print('generated canonical appium script')"
    assert captured["methods_script"] == "print('generated canonical appium script')"
    assert captured["methods_framework"] == "appium"
    assert captured["methods_language"] == "python"


def test_single_run_artifacts_keep_final_script_as_canonical_sync_source(tmp_path, monkeypatch):
    zip_path = tmp_path / "single_run_artifacts.zip"
    write_executor_zip(zip_path)
    captured = {}

    async def fake_sync_testcaserag(*, final_script_content, testcase_payload, canonical_testcase_id, mode, req_logger):
        captured["sync_script"] = final_script_content
        return {
            "status": "ingested",
            "canonical_testcase_id": canonical_testcase_id,
            "script_id": "script-1",
        }

    async def fake_extract_and_upload_methods(final_script_content, req_logger, *, framework=None, language=None):
        captured["methods_script"] = final_script_content
        captured["methods_framework"] = framework
        captured["methods_language"] = language
        return "uploaded"

    monkeypatch.setattr(PipelineService, "_sync_testcaserag", staticmethod(fake_sync_testcaserag))
    monkeypatch.setattr(PipelineService, "_extract_and_upload_methods", staticmethod(fake_extract_and_upload_methods))

    asyncio.run(
        PipelineService._persist_generated_artifacts(
            zip_path=zip_path,
            testcase_payload=sample_testcase_payload(),
            canonical_testcase_id="tc-new",
            mode="new",
            generated_script_content="print('generated fallback script')\n",
            req_logger=NullLogger(),
        )
    )

    expected = "async def _step_0_abcdef123456(page):\n    await page.click('text=Login')"
    assert captured["sync_script"].strip() == expected
    assert captured["methods_script"].strip() == expected
    assert captured["methods_framework"] == "playwright"
    assert captured["methods_language"] == "python"


def test_executor_zip_metadata_enrichment_reads_matrix_summary_and_failed_step(tmp_path):
    zip_path = tmp_path / "matrix_artifacts.zip"
    write_matrix_executor_zip(zip_path)

    metadata = PipelineService._enrich_executor_metadata_from_zip(
        zip_path,
        {"executor_status": "failed"},
    )

    assert metadata["executor_status"] == "failed"
    assert metadata["executor_artifact_kind"] == "appium_device_matrix"
    assert metadata["executor_matrix_run_count"] == 2
    assert metadata["executor_failed_step_index"] == 3


def install_pipeline_mocks(monkeypatch, events, search_result, executor_status="passed"):
    linked = {}

    async def search(testcase_payload, req_logger):
        events.append("search")
        return search_result

    async def fetch(script_id, req_logger=None):
        events.append(f"fetch:{script_id}")
        return "async def _step_0_abcdef123456(page):\n    pass\n"

    async def generate(testcase_payload, script_path, request_id, req_logger):
        events.append("generate_script")
        script_path.write_text("async def _step_0_abcdef123456(page):\n    pass\n", encoding="utf-8")

    async def execute(script_path, zip_path, request_id, req_logger, *, framework=None, testcase_payload=None):
        events.append("execute")
        assert script_path.exists()
        assert framework == "playwright"
        write_executor_zip(zip_path)
        return {
            "executor_status": executor_status,
            "executor_run_id": "run-1",
            "executor_duration": "12",
        }

    async def generate_report(zip_path, request_id, req_logger):
        events.append("generate_report")
        assert zip_path.exists()
        return "<html>report</html>"

    async def upload_report(html_output, testcase_name, request_id, req_logger):
        events.append("upload_report")
        assert html_output == "<html>report</html>"
        return "report-1"

    async def persist_generated_artifacts(*, zip_path, testcase_payload, canonical_testcase_id, mode, generated_script_content, req_logger):
        events.append(f"persist:{mode}")
        assert zip_path.exists()
        assert generated_script_content.strip()
        return {
            "testcase_rag_status": "synced" if mode == "existing" else "ingested",
            "methods_rag_status": "uploaded",
            "canonical_testcase_id": canonical_testcase_id if mode == "existing" else "tc-new-canonical",
        }

    async def link_report_history(**kwargs):
        events.append("link_report")
        linked.update(kwargs)

    monkeypatch.setattr(PipelineService, "_search_existing_testcase", staticmethod(search))
    monkeypatch.setattr(PipelineService, "_fetch_script", staticmethod(fetch))
    monkeypatch.setattr(PipelineService, "_generate_script", staticmethod(generate))
    monkeypatch.setattr(PipelineService, "_execute_script", staticmethod(execute))
    monkeypatch.setattr(PipelineService, "_generate_report", staticmethod(generate_report))
    monkeypatch.setattr(PipelineService, "_upload_report", staticmethod(upload_report))
    monkeypatch.setattr(PipelineService, "_persist_generated_artifacts", staticmethod(persist_generated_artifacts))
    monkeypatch.setattr(PipelineService, "_link_report_history", staticmethod(link_report_history))
    return linked


def test_match_above_85_with_script_uses_existing_script_path(monkeypatch):
    events = []
    linked = install_pipeline_mocks(
        monkeypatch,
        events,
        {"id": "tc-existing", "probability": 86.0, "playwright_script_id": "script-1"},
    )

    result = asyncio.run(PipelineService.execute_run(sample_testcase_payload(), "req-existing"))

    assert result["routing_path"] == "existing_script"
    assert result["matched_probability"] == 86.0
    assert result["canonical_testcase_id"] == "tc-existing"
    assert result["testcase_rag_status"] == "not_required"
    assert result["methods_rag_status"] == "not_required"
    assert result["executor_artifact_kind"] == "single_run"
    assert events == ["search", "fetch:script-1", "execute", "generate_report", "upload_report", "link_report"]
    assert linked["canonical_testcase_id"] == "tc-existing"


def test_match_above_85_without_script_generates_then_syncs_after_report(monkeypatch):
    events = []
    install_pipeline_mocks(
        monkeypatch,
        events,
        {"id": "tc-existing", "probability": 88.0},
    )

    result = asyncio.run(PipelineService.execute_run(sample_testcase_payload(), "req-missing-script"))

    assert result["routing_path"] == "existing_missing_script_generated"
    assert result["canonical_testcase_id"] == "tc-existing"
    assert result["testcase_rag_status"] == "synced"
    assert result["methods_rag_status"] == "uploaded"
    assert events == [
        "search",
        "generate_script",
        "execute",
        "generate_report",
        "upload_report",
        "persist:existing",
        "link_report",
    ]


def test_no_match_generates_reports_then_ingests_and_uploads_methods(monkeypatch):
    events = []
    install_pipeline_mocks(monkeypatch, events, None, executor_status="failed")

    result = asyncio.run(PipelineService.execute_run(sample_testcase_payload(), "req-new"))

    assert result["routing_path"] == "new_generated"
    assert result["matched_probability"] is None
    assert result["canonical_testcase_id"] == "tc-new-canonical"
    assert result["report_id"] == "report-1"
    assert result["executor_status"] == "failed"
    assert result["testcase_rag_status"] == "ingested"
    assert result["methods_rag_status"] == "uploaded"
    assert events == [
        "search",
        "generate_script",
        "execute",
        "generate_report",
        "upload_report",
        "persist:new",
        "link_report",
    ]
