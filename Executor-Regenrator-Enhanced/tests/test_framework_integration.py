import pytest
import json
import logging
import warnings
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
from app.models.step_repair import StepRepairRequest, ErrorClassification, ErrorDetails, Artifacts
from app.services.repair_pipeline import execute_repair_pipeline
from app.services.step_verifier import StepVerifier
from app.services.llm_fallback_repair import LLMFallbackRepairEngine
from app.core.exceptions import StepNotRepairableError

@pytest.mark.asyncio
async def test_selenium_pipeline_uses_primary_before_fallback(mock_llm_executor):
    """Selenium repairs now use the primary CIR path first."""
    request = StepRepairRequest(
        step_id="step_1__test_selenium_flow",
        step_intent="Click the submit button",
        original_code="driver.find_element(By.ID, 'sub').click()",
        error_classification=ErrorClassification(type="LOCATOR_NOT_FOUND"),
        error_details=ErrorDetails(message="NoSuchElementException: Message: no such element: Unable to locate element"),
        framework="selenium",
        artifacts=Artifacts(error_text="no such element", dom_snapshot="<html><body><button id='submit'>Submit</button></body></html>")
    )

    mock_llm_executor.run_classifier.return_value = "click"
    mock_llm_executor.run_extractor.return_value = 'click:css("#submit")'
    mock_llm_executor.run_verifier_structured.return_value = (
        '{"verdict": "correct", "reason": "Selenium locator updated to matching ID"}'
    )

    with patch("app.core.llm_executor.LLMExecutor.get_instance", return_value=mock_llm_executor):
        repaired_code, action_type = await execute_repair_pipeline(
            request=request,
            error_image_bytes=None,
            request_id="req_selenium_e2e_123"
        )

        assert "driver.find_element(By.CSS_SELECTOR, '#submit')" in repaired_code
        assert "element.click()" in repaired_code
        assert action_type == "primary"
        assert not mock_llm_executor.run_modifier.called
        assert mock_llm_executor.run_verifier_structured.called


@pytest.mark.asyncio
async def test_non_playwright_pipeline_falls_back_only_after_primary_fails(mock_llm_executor):
    """Fallback remains available, but only after primary is unable to repair."""
    request = StepRepairRequest(
        step_id="step_1__test_selenium_flow",
        step_intent="Click the submit button",
        original_code="driver.find_element(By.ID, 'sub').click()",
        error_classification=ErrorClassification(type="LOCATOR_NOT_FOUND"),
        error_details=ErrorDetails(message="NoSuchElementException: Message: no such element: Unable to locate element"),
        framework="selenium",
        artifacts=Artifacts(error_text="no such element", dom_snapshot="<html><body><button id='submit'>Submit</button></body></html>")
    )

    healed_code = "driver.find_element(By.ID, 'submit').click()"
    mock_llm_executor.run_classifier.return_value = "click"
    mock_llm_executor.run_extractor.return_value = "none"
    mock_llm_executor.run_modifier.return_value = healed_code
    mock_llm_executor.run_verifier_structured.return_value = (
        '{"verdict": "correct", "reason": "Selenium locator updated to matching ID"}'
    )

    with patch("app.core.llm_executor.LLMExecutor.get_instance", return_value=mock_llm_executor):
        repaired_code, action_type = await execute_repair_pipeline(
            request=request,
            error_image_bytes=None,
            request_id="req_selenium_fallback_123"
        )

        assert repaired_code.strip() == healed_code.strip()
        assert action_type == "llm_fallback"
        assert mock_llm_executor.run_modifier.called
        assert mock_llm_executor.run_verifier_structured.called


def test_sandbox_whitelists_selenium_and_appium():
    """Verifies AST security validation allows selenium and appium imports."""
    from app.executors.sandbox import ScriptSecurityValidator
    validator = ScriptSecurityValidator(strict_mode=True)
    
    # Selenium imports
    selenium_script = "import selenium\nfrom selenium.webdriver.common.by import By\nprint('selenium')"
    is_safe, reason = validator.validate(selenium_script)
    assert is_safe, f"Selenium should be allowed: {reason}"
    
    # Appium imports
    appium_script = """
import os
import sys
import json
import time
import hashlib
import traceback
import re
import base64
from datetime import datetime, timezone
from appium import webdriver
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from appium.options.common.base import AppiumOptions
print('appium')
"""
    is_safe, reason = validator.validate(appium_script)
    assert is_safe, f"Appium should be allowed: {reason}"


def test_auto_repair_trigger_reads_appium_dom_xml(tmp_path):
    """Verifies Appium dom.xml snapshots are available to repair prompts."""
    from app.services.auto_repair_trigger import AutoRepairTrigger

    artifacts_dir = tmp_path / "artifacts"
    run_dir = artifacts_dir / "TC_MOBILE_001" / "run123"
    failures_dir = run_dir / "failures"
    attempt_dir = failures_dir / "iphone_latest" / "0_iphone_latest__step_0_abc123_iphone_latest" / "attempt_1"
    attempt_dir.mkdir(parents=True)

    (run_dir / "status.txt").write_text("failed", encoding="utf-8")
    (failures_dir / "summary.json").write_text(
        json.dumps(
            {
                "status": "failed",
                "failed_step_index": 0,
                "failed_device_slug": "iphone_latest",
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "step_code.py").write_text(
        "element = driver.find_element(AppiumBy.ACCESSIBILITY_ID, 'Login')\nelement.click()",
        encoding="utf-8",
    )
    (attempt_dir / "intent.txt").write_text("Tap Login", encoding="utf-8")
    (attempt_dir / "error.txt").write_text("NoSuchElementException", encoding="utf-8")
    (attempt_dir / "traceback.txt").write_text("Traceback", encoding="utf-8")
    (attempt_dir / "dom.xml").write_text("<hierarchy><node text=\"Login\" /></hierarchy>", encoding="utf-8")
    (attempt_dir / "device_context.json").write_text(
        json.dumps(
            {
                "label": "iPhone Latest",
                "device_name": "iPhone 15 Pro Max",
                "platform_name": "iOS",
                "bundle_id": "com.example.ios",
            }
        ),
        encoding="utf-8",
    )

    request = AutoRepairTrigger().build_request_from_artifacts(str(artifacts_dir))

    assert request is not None
    assert request.step_id == "0_iphone_latest__step_0_abc123_iphone_latest"
    assert request.artifacts.dom_snapshot == "<hierarchy><node text=\"Login\" /></hierarchy>"
    assert "device_label=iPhone Latest" in request.step_intent
    assert "platform=iOS" in request.step_intent


def test_executor_selects_appium_runtime_devices_and_builds_device_env():
    from app.routes.executor import (
        _build_appium_device_runtime_env,
        _select_appium_runtime_devices,
    )

    devices = _select_appium_runtime_devices(
        appium_device_filter="Pixel 7",
        appium_device_matrix=json.dumps(
            {
                "devices": [
                    {
                        "label": "Pixel 7",
                        "device_name": "Google Pixel 7",
                        "platform_name": "Android",
                        "app": "bs://ANDROID_APP_ID",
                        "capabilities": {
                            "bstack:options": {
                                "projectName": "Executor-Regenerator"
                            }
                        },
                    },
                    {
                        "label": "iPhone Latest",
                        "device_name": "iPhone 15 Pro Max",
                        "platform_name": "iOS",
                        "bundle_id": "com.example.ios",
                        "app": "bs://IOS_APP_ID",
                    },
                ]
            }
        ),
    )

    assert len(devices) == 1
    assert devices[0]["slug"] == "pixel_7"
    env = _build_appium_device_runtime_env(
        device=devices[0],
        appium_server_url="https://user:key@hub-cloud.browserstack.com/wd/hub",
    )

    assert env["APPIUM_SERVER_URL"] == "https://user:key@hub-cloud.browserstack.com/wd/hub"
    assert env["APPIUM_DEVICE_LABEL"] == "Pixel 7"
    capabilities = json.loads(env["APPIUM_CAPABILITIES_JSON"])
    assert capabilities["appium:deviceName"] == "Google Pixel 7"
    assert capabilities["appium:app"] == "bs://ANDROID_APP_ID"
    assert capabilities["bstack:options"]["projectName"] == "Executor-Regenerator"


def test_executor_rejects_invalid_appium_matrix_json():
    from fastapi import HTTPException
    from app.routes.executor import _select_appium_runtime_devices

    with pytest.raises(HTTPException) as exc:
        _select_appium_runtime_devices(
            appium_device_filter=None,
            appium_device_matrix="{not json",
        )

    assert exc.value.status_code == 400


def test_executor_uses_default_appium_matrix_file_when_request_omits_matrix(tmp_path, monkeypatch):
    from app.routes.executor import _select_appium_runtime_devices

    matrix_path = tmp_path / "appium_device_matrix.json"
    matrix_path.write_text(
        json.dumps(
            {
                "devices": [
                    {
                        "label": "Pixel 7 Local GCP",
                        "slug": "pixel_7_local_gcp",
                        "device_name": "Pixel_7_API_36",
                        "platform_name": "Android",
                        "udid": "emulator-5554",
                        "app_package": "com.google.android.deskclock",
                        "app_activity": "com.android.deskclock.DeskClock",
                        "app_wait_activity": "*",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("APPIUM_DEVICE_MATRIX_JSON", raising=False)
    monkeypatch.setenv("APPIUM_DEVICE_MATRIX_PATH", str(matrix_path))

    devices = _select_appium_runtime_devices(
        appium_device_filter=None,
        appium_device_matrix=None,
    )

    assert len(devices) == 1
    assert devices[0]["slug"] == "pixel_7_local_gcp"
    assert devices[0]["device_name"] == "Pixel_7_API_36"


def test_executor_request_matrix_overrides_default_appium_matrix_file(tmp_path, monkeypatch):
    from app.routes.executor import _select_appium_runtime_devices

    matrix_path = tmp_path / "appium_device_matrix.json"
    matrix_path.write_text(
        json.dumps(
            {
                "devices": [
                    {
                        "label": "Pixel 7 Local GCP",
                        "slug": "pixel_7_local_gcp",
                        "device_name": "Pixel_7_API_36",
                        "platform_name": "Android",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("APPIUM_DEVICE_MATRIX_JSON", raising=False)
    monkeypatch.setenv("APPIUM_DEVICE_MATRIX_PATH", str(matrix_path))

    devices = _select_appium_runtime_devices(
        appium_device_filter=None,
        appium_device_matrix=json.dumps(
            {
                "devices": [
                    {
                        "label": "iPhone Latest",
                        "slug": "iphone_latest",
                        "device_name": "iPhone 15 Pro Max",
                        "platform_name": "iOS",
                        "bundle_id": "com.example.ios",
                    }
                ]
            }
        ),
    )

    assert len(devices) == 1
    assert devices[0]["slug"] == "iphone_latest"
    assert devices[0]["platform_name"] == "iOS"


@pytest.mark.asyncio
async def test_async_executor_materializes_bootstrap_failure_when_script_never_writes_status(tmp_path):
    from app.executors.python import AsyncPythonExecutor

    script_file = tmp_path / "broken_import.py"
    script_file.write_text(
        "import definitely_missing_dependency_for_executor_status_regression\n",
        encoding="utf-8",
    )

    executor = AsyncPythonExecutor(
        timeout_seconds=10,
        base_work_dir=str(tmp_path / "executor_work"),
        enable_sandbox=False,
    )

    result = await executor.execute(str(script_file))

    run_dir = Path(result.working_dir)
    execution_dir = run_dir / "artifacts" / "bootstrap" / result.run_id
    summary_path = execution_dir / "failures" / "summary.json"
    traceback_path = execution_dir / "failures" / "startup" / "traceback.txt"

    assert result.success is False
    assert result.semantic_status == "failed"
    assert (execution_dir / "status.txt").read_text(encoding="utf-8").strip() == "failed"

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["bootstrap_failure"] is True
    assert summary["failed_step_index"] is None
    assert "before writing status.txt" in summary["failure_reason"]
    assert "definitely_missing_dependency_for_executor_status_regression" in summary["startup_error"]
    assert "ModuleNotFoundError" in traceback_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_async_executor_renames_framework_named_script_to_avoid_module_shadowing(tmp_path):
    from app.executors.python import AsyncPythonExecutor

    fake_site = tmp_path / "fake_site"
    fake_appium = fake_site / "appium"
    fake_appium.mkdir(parents=True)
    (fake_appium / "__init__.py").write_text(
        "class webdriver:\n    pass\n",
        encoding="utf-8",
    )

    script_file = tmp_path / "appium.py"
    script_file.write_text(
        "\n".join(
            [
                "import os",
                "from pathlib import Path",
                "from appium import webdriver",
                "artifacts_dir = Path(os.environ['ARTIFACTS_DIR'])",
                "artifacts_dir.mkdir(parents=True, exist_ok=True)",
                "(artifacts_dir / 'status.txt').write_text('passed', encoding='utf-8')",
                "print(webdriver.__name__)",
            ]
        ),
        encoding="utf-8",
    )

    executor = AsyncPythonExecutor(
        timeout_seconds=10,
        base_work_dir=str(tmp_path / "executor_work"),
        enable_sandbox=False,
    )

    result = await executor.execute(
        str(script_file),
        extra_env={"PYTHONPATH": str(fake_site)},
    )

    executed_script = Path(result.command[1])

    assert result.success is True
    assert result.semantic_status == "passed"
    assert executed_script.name == "executed_appium_script.py"
    assert "webdriver" in result.stdout


def test_docker_cmd_builder_whitelists_non_playwright_prefixes():
    """Verifies AsyncPythonExecutor._build_docker_cmd whitelists non-Playwright environment variable prefixes."""
    from app.executors.python import AsyncPythonExecutor
    
    executor = AsyncPythonExecutor()
    env = {
        "PW_TEST": "1",
        "SELENIUM_URL": "http://selenium",
        "SE_VAR": "value",
        "CYPRESS_RUN": "yes",
        "CY_VAR": "cy",
        "APPIUM_PORT": "4723",
        "WD_CAPS": "caps",
        "WEBDRIVER_PATH": "/path",
        "SECRET_API_KEY": "should_be_stripped"
    }
    
    cmd = executor._build_docker_cmd(
        run_dir=Path("/workspace"),
        script_name="test_script.py",
        run_id="run123",
        env=env
    )
    
    # Verify whitelisted env vars are included in docker run command
    assert "-e" in cmd
    cmd_str = " ".join(cmd)
    assert "PW_TEST=1" in cmd_str
    assert "SELENIUM_URL=http://selenium" in cmd_str
    assert "SE_VAR=value" in cmd_str
    assert "CYPRESS_RUN=yes" in cmd_str
    assert "CY_VAR=cy" in cmd_str
    assert "APPIUM_PORT=4723" in cmd_str
    assert "WD_CAPS=caps" in cmd_str
    assert "WEBDRIVER_PATH=/path" in cmd_str
    # Non-whitelisted env vars should be stripped
    assert "SECRET_API_KEY" not in cmd_str


@pytest.mark.asyncio
async def test_step_verifier_returns_correct_verdict_from_structured_output():
    """StepVerifier uses run_verifier_structured; a correct schema-valid response yields passed=True."""
    class DummyLLM:
        async def run_verifier_structured(self, prompt, schema):
            return '{"verdict":"correct","reason":"The locator typo was fixed."}'

    verifier = StepVerifier(llm=DummyLLM())
    result = await verifier.verify(
        intent="Locate the 7:30 alarm",
        generated_code='element = driver.find_element(AppiumBy.XPATH, "//*[contains(@text, \'7:30\')]")',
        matched_script=None,
        framework="appium",
    )

    assert result["verdict"] == "correct"
    assert result.passed is True
    assert "typo" in result["reason"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("structured_response", "expected_verdict"),
    [
        ('{"verdict":"correct","reason":"locator is valid"}', "correct"),
        ('{"verdict":"incorrect","reason":"wrong selector used"}', "incorrect"),
        (None, "incorrect"),
        ("not valid json", "incorrect"),
    ],
)
async def test_step_verifier_handles_structured_output_shapes(structured_response, expected_verdict):
    """StepVerifier parses schema-valid JSON and falls back gracefully on empty/invalid responses."""
    class DummyLLM:
        async def run_verifier_structured(self, prompt, schema):
            return structured_response

    verifier = StepVerifier(llm=DummyLLM())
    result = await verifier.verify(
        intent="Tap London",
        generated_code='element = driver.find_element(AppiumBy.ACCESSIBILITY_ID, "London")',
        matched_script=None,
        error_message="NoSuchElementException",
        framework="appium",
    )

    assert result["verdict"] == expected_verdict


def test_dom_pruner_parses_appium_xml_without_html_warning():
    """Appium page source is XML and should not be parsed through the noisy HTML path."""
    from bs4 import XMLParsedAsHTMLWarning
    from app.core.dom_pruner import DomPruner

    dom = """<?xml version='1.0' encoding='UTF-8'?>
<hierarchy>
  <android.widget.TextView text="7:30 AM" content-desc="7:30 AM" resource-id="clock:id/digital_clock" clickable="true" enabled="true" />
</hierarchy>"""

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        pruned = DomPruner.prune(dom, "7:30", framework="appium")

    assert pruned
    assert "7:30 AM" in pruned
    assert not any(issubclass(item.category, XMLParsedAsHTMLWarning) for item in caught)


def test_appium_click_extractor_rejects_web_locators_and_accepts_native():
    from app.services.extractors.ClickExtractor import ClickActionExtractor
    from app.models.cir import LocatorStrategy

    extractor = ClickActionExtractor()
    extractor._last_step_intent = "Tap London"
    extractor._last_original_code = ""
    extractor._last_dom_snapshot = (
        '<hierarchy><android.widget.TextView resource-id="com.android.deskclock:id/city_name" '
        'content-desc="London" text="London" /></hierarchy>'
    )

    assert extractor._normalize_llm_hint('click:role("button", name="London")', framework="appium") is None
    assert extractor._normalize_llm_hint('click:css("#city_name")', framework="appium") is None

    by_id = extractor._normalize_llm_hint(
        'click:id("com.android.deskclock:id/city_name")',
        framework="appium",
    )
    by_accessibility = extractor._normalize_llm_hint(
        'click:accessibility_id("London")',
        framework="appium",
    )
    by_uiautomator = extractor._normalize_llm_hint(
        'click:uiautomator("new UiSelector().text(\\"London\\")")',
        framework="appium",
    )

    assert by_id.strategy == LocatorStrategy.id
    assert by_accessibility.strategy == LocatorStrategy.test_id
    assert by_uiautomator.strategy == LocatorStrategy.uiautomator


def test_fallback_repair_prompt_keeps_appium_framework():
    """Fallback repair prompts for Appium must not silently become Playwright prompts."""
    engine = object.__new__(LLMFallbackRepairEngine)

    prompt = engine._build_prompt(
        step_intent="Locate the 7:30 alarm",
        current_code='element = driver.find_element(AppiumBy.XPATH, "//*[contains(@text, \'7::30\')]")',
        error_text="NoSuchElementException",
        dom_snapshot="<hierarchy><android.widget.TextView text='7:30 AM' /></hierarchy>",
        framework="appium",
    )

    assert "Repair the failed Appium step" in prompt


def test_orchestrator_warns_on_step_function_and_guarded_source_mismatch(tmp_path, caplog):
    from app.services.execution_orchestrator import SelfHealingExecutorOrchestrator

    script_file = tmp_path / "appium_mismatch.py"
    script_file.write_text(
        """from appium.webdriver.common.appiumby import AppiumBy

def _step_6_d74d7f3751ed(driver):
    element = driver.find_element(AppiumBy.XPATH, "//*[contains(@text, '7::30')]")
    assert element.is_displayed()

def test_flow():
    _guarded_step(driver, _step_6_d74d7f3751ed, '6__step_6_d74d7f3751ed', 6, "element = driver.find_element(AppiumBy.XPATH, \\"//*[contains(@text, '7:30')]\\")\\nassert element.is_displayed()", "Locate the 7:30 alarm", 1)
""",
        encoding="utf-8",
    )

    orchestrator = SelfHealingExecutorOrchestrator(
        executor=MagicMock(),
        repair_trigger=MagicMock(),
        repair_service=MagicMock(),
        patcher=MagicMock(),
    )

    with caplog.at_level(logging.WARNING):
        orchestrator._warn_guarded_step_source_mismatches(
            script_path=str(script_file),
            framework="appium",
        )

    assert "SCRIPT_SOURCE_MISMATCH" in caplog.text
    assert "6__step_6_d74d7f3751ed" in caplog.text


def test_orchestrator_ignores_assertion_comments_in_guarded_source(tmp_path, caplog):
    from app.services.execution_orchestrator import SelfHealingExecutorOrchestrator

    script_file = tmp_path / "appium_comment_match.py"
    script_file.write_text(
        """from appium.webdriver.common.appiumby import AppiumBy

def _step_0_same(driver):
    element = driver.find_element(AppiumBy.ACCESSIBILITY_ID, "World Clock")
    assert element.is_displayed()

def test_flow():
    _guarded_step(driver, _step_0_same, '0__step_0_same', 0, "# [ASSERT]\\nelement = driver.find_element(AppiumBy.ACCESSIBILITY_ID, \\"World Clock\\")\\nassert element.is_displayed()", "Assert World Clock is visible", 1)
""",
        encoding="utf-8",
    )

    orchestrator = SelfHealingExecutorOrchestrator(
        executor=MagicMock(),
        repair_trigger=MagicMock(),
        repair_service=MagicMock(),
        patcher=MagicMock(),
    )

    with caplog.at_level(logging.WARNING):
        orchestrator._warn_guarded_step_source_mismatches(
            script_path=str(script_file),
            framework="appium",
        )

    assert "SCRIPT_SOURCE_MISMATCH" not in caplog.text


@pytest.mark.asyncio
async def test_appium_pipeline_stops_before_fallback_when_target_is_missing_from_screen():
    request = StepRepairRequest(
        step_id="19__step_19_timer_digit",
        step_intent="Tap digit 1 in the timer keypad",
        original_code='element = driver.find_element(AppiumBy.XPATH, "//*[contains(@text, \'1\')]")\nelement.click()',
        error_classification=ErrorClassification(type="LOCATOR_NOT_FOUND"),
        error_details=ErrorDetails(message="NoSuchElementError: Unable to locate element"),
        framework="appium",
        artifacts=Artifacts(
            error_text="NoSuchElementError",
            dom_snapshot='<hierarchy><node content-desc="Add timer" text="Add timer" /></hierarchy>',
        ),
    )

    with patch(
        "app.services.repair_pipeline._run_primary_repair",
        new=AsyncMock(side_effect=StepNotRepairableError("Click inferred but no locator extracted")),
    ), patch(
        "app.services.repair_pipeline._run_fallback_repair",
        new=AsyncMock(return_value=("fallback", "llm_fallback")),
    ) as fallback_mock:
        with pytest.raises(StepNotRepairableError) as exc:
            await execute_repair_pipeline(
                request=request,
                error_image_bytes=None,
                request_id="req_appium_state_mismatch",
            )

    assert "UI state mismatch" in str(exc.value)
    fallback_mock.assert_not_awaited()


def test_appium_matrix_zip_skips_duplicate_capabilities_entry(tmp_path):
    from types import SimpleNamespace
    from app.routes.executor_routes.common import _write_appium_matrix_zip

    run_dir = tmp_path / "failed_runs" / "pixel_7_local_gcp"
    run_dir.mkdir(parents=True)
    (run_dir / "appium_capabilities.json").write_text(
        json.dumps({"appium:deviceName": "Pixel_7_API_36"}),
        encoding="utf-8",
    )
    failures_dir = run_dir / "failures"
    failures_dir.mkdir()
    (failures_dir / "summary.json").write_text(
        json.dumps({"failed_step_index": 19}),
        encoding="utf-8",
    )

    zip_path = _write_appium_matrix_zip(
        matrix_run_id="matrix_dup_check",
        matrix_results=[
            {
                "device": {
                    "label": "Pixel 7 Local GCP",
                    "slug": "pixel_7_local_gcp",
                    "platform_name": "Android",
                    "device_name": "Pixel_7_API_36",
                    "capabilities": {"appium:deviceName": "Pixel_7_API_36"},
                },
                "result": SimpleNamespace(
                    run_id="run_123",
                    semantic_status="failed",
                ),
                "duration_ms": 321,
                "run_dir": run_dir,
            }
        ],
        semantic_status="failed",
    )

    with zipfile.ZipFile(zip_path) as zipf:
        names = zipf.namelist()

    assert names.count("pixel_7_local_gcp/appium_capabilities.json") == 1


@pytest.mark.asyncio
async def test_orchestrator_uses_primary_repair_for_appium_before_fallback(tmp_path, monkeypatch):
    from app.executors.models import ExecutionOutcome, ExecutionResult
    from app.services.execution_orchestrator import SelfHealingExecutorOrchestrator

    script_file = tmp_path / "appium_primary.py"
    script_file.write_text(
        """def step_1_test(driver):
    element = driver.find_element("id", "old")
    element.click()
""",
        encoding="utf-8",
    )

    failed_working_dir = tmp_path / "runs" / "failed_run"
    failed_status_dir = failed_working_dir / "artifacts" / "TC_APPIUM" / "failed_run"
    failed_status_dir.mkdir(parents=True)
    (failed_status_dir / "status.txt").write_text("failed", encoding="utf-8")

    passed_working_dir = tmp_path / "runs" / "passed_run"
    passed_status_dir = passed_working_dir / "artifacts" / "TC_APPIUM" / "passed_run"
    passed_status_dir.mkdir(parents=True)
    (passed_status_dir / "status.txt").write_text("passed", encoding="utf-8")

    failed_result = ExecutionResult(
        success=False,
        exit_code=1,
        stdout="",
        stderr="NoSuchElementException",
        duration_ms=100,
        timed_out=False,
        command=["python", str(script_file)],
        working_dir=str(failed_working_dir),
        artifacts_dir=str(failed_working_dir / "artifacts"),
        script_path=str(script_file),
        run_id="failed_run",
        semantic_status="failed",
        outcome=ExecutionOutcome.FAILURE,
    )
    passed_result = ExecutionResult(
        success=True,
        exit_code=0,
        stdout="passed",
        stderr="",
        duration_ms=100,
        timed_out=False,
        command=["python", str(script_file)],
        working_dir=str(passed_working_dir),
        artifacts_dir=str(passed_working_dir / "artifacts"),
        script_path=str(script_file),
        run_id="passed_run",
        semantic_status="passed",
        outcome=ExecutionOutcome.SUCCESS,
    )

    mock_executor = AsyncMock()
    mock_executor.execute.side_effect = [failed_result, passed_result]

    mock_trigger = MagicMock()
    mock_trigger.build_request_from_artifacts.return_value = StepRepairRequest(
        step_id="1__step_1_test",
        step_intent="Tap the fixed Appium element",
        original_code='element = driver.find_element(AppiumBy.ID, "old")\nelement.click()',
        error_classification=ErrorClassification(type="LOCATOR_NOT_FOUND"),
        error_details=ErrorDetails(message="NoSuchElementException"),
        artifacts=Artifacts(
            error_text="NoSuchElementException",
            dom_snapshot='<hierarchy><node resource-id="new" text="Fixed" /></hierarchy>',
        ),
    )

    mock_repair_service = MagicMock()
    mock_repair_service.repair_step = AsyncMock(
        return_value=('element = driver.find_element(AppiumBy.ID, "new")\nelement.click()', "primary")
    )

    mock_patcher = MagicMock()
    mock_patcher.patch_step.return_value = str(tmp_path / "backup.py")

    orchestrator = SelfHealingExecutorOrchestrator(
        executor=mock_executor,
        repair_trigger=mock_trigger,
        repair_service=mock_repair_service,
        patcher=mock_patcher,
    )
    orchestrator.backoff.compute = lambda attempt: 0

    mock_explainer = MagicMock()
    mock_explainer.generate_explanation = AsyncMock(return_value={"summary": "primary repaired"})
    monkeypatch.setattr(orchestrator, "_explainer", mock_explainer)

    final_result = await orchestrator.execute_script_with_self_healing(
        script_path=str(script_file),
        framework_override="appium",
    )

    assert final_result.semantic_status == "passed"
    mock_repair_service.repair_step.assert_awaited_once()
    assert mock_repair_service.repair_step.await_args.kwargs["request"].framework == "appium"
    mock_patcher.patch_step.assert_called_once()
    assert final_result.metadata["repair_history"][0]["outcome"] == "rerun_passed"


@pytest.mark.asyncio
async def test_orchestrator_does_not_call_fallback_directly_when_pipeline_cannot_repair(tmp_path, monkeypatch):
    from app.executors.models import ExecutionOutcome, ExecutionResult
    from app.services.execution_orchestrator import SelfHealingExecutorOrchestrator

    script_file = tmp_path / "appium_unrepairable.py"
    script_file.write_text("def _step_0_bad(driver):\n    raise RuntimeError('bad')\n", encoding="utf-8")

    working_dir = tmp_path / "runs" / "failed_run"
    status_dir = working_dir / "artifacts" / "TC_APPIUM" / "failed_run"
    status_dir.mkdir(parents=True)
    (status_dir / "status.txt").write_text("failed", encoding="utf-8")

    failed_result = ExecutionResult(
        success=False,
        exit_code=1,
        stdout="",
        stderr="NoSuchElementException",
        duration_ms=100,
        timed_out=False,
        command=["python", str(script_file)],
        working_dir=str(working_dir),
        artifacts_dir=str(working_dir / "artifacts"),
        script_path=str(script_file),
        run_id="failed_run",
        semantic_status="failed",
        outcome=ExecutionOutcome.FAILURE,
    )

    mock_executor = AsyncMock()
    mock_executor.execute.return_value = failed_result

    mock_trigger = MagicMock()
    mock_trigger.build_request_from_artifacts.return_value = StepRepairRequest(
        step_id="0__step_0_bad",
        step_intent="Tap missing element",
        original_code="raise RuntimeError('bad')",
        error_classification=ErrorClassification(type="LOCATOR_NOT_FOUND"),
        error_details=ErrorDetails(message="NoSuchElementException"),
        artifacts=Artifacts(error_text="NoSuchElementException", dom_snapshot="<hierarchy />"),
    )

    mock_repair_service = MagicMock()
    mock_repair_service.repair_step = AsyncMock(side_effect=StepNotRepairableError("not repairable"))

    orchestrator = SelfHealingExecutorOrchestrator(
        executor=mock_executor,
        repair_trigger=mock_trigger,
        repair_service=mock_repair_service,
        patcher=MagicMock(),
    )
    mock_explainer = MagicMock()
    mock_explainer.generate_explanation = AsyncMock(return_value={"summary": "not repairable"})
    monkeypatch.setattr(orchestrator, "_explainer", mock_explainer)

    assert not hasattr(orchestrator, "fallback_repair")

    final_result = await orchestrator.execute_script_with_self_healing(
        script_path=str(script_file),
        framework_override="appium",
    )

    assert final_result.semantic_status == "failed"
    assert final_result.metadata["repair_history"][0]["outcome"] == "permanent_failure"
    mock_repair_service.repair_step.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_runs_archiving_and_reasons(tmp_path, monkeypatch):
    """Verifies that failed executions are archived under failed_runs/ containing explanation and report json."""
    # Set up mocks for execution result and orchestrator
    from app.services.execution_orchestrator import SelfHealingExecutorOrchestrator, ExecutorOrchestratorConfig
    from app.executors.models import ExecutionResult, ExecutionOutcome
    from app.models.step_repair import StepRepairRequest, ErrorClassification, ErrorDetails, Artifacts
    
    # Mock directories
    artifacts_root = tmp_path
    config = ExecutorOrchestratorConfig(
        max_repairs_per_step=1,
        artifacts_root=artifacts_root
    )
    
    # Write status.txt as failed
    run_id = "failed_run_123"
    working_dir = tmp_path / "runs" / run_id
    working_dir.mkdir(parents=True, exist_ok=True)
    
    # Recreate the real nested directory structure
    artifacts_dir = working_dir / "artifacts" / "TC_TEST_001" / run_id
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    
    status_file = artifacts_dir / "status.txt"
    status_file.write_text("failed")
    
    # Mock execution result
    mock_result = ExecutionResult(
        success=False,
        exit_code=1,
        stdout="stdout logs",
        stderr="stderr exception",
        duration_ms=100,
        timed_out=False,
        command=["python", "test.py"],
        working_dir=str(working_dir),
        artifacts_dir=str(working_dir / "artifacts"),
        script_path=str(working_dir / "test.py"),
        run_id=run_id,
        semantic_status="failed",
        outcome=ExecutionOutcome.FAILURE
    )
    
    mock_executor = AsyncMock()
    mock_executor.execute.return_value = mock_result
    
    mock_trigger = MagicMock()
    # Trigger returns a request to trigger healing loop
    mock_trigger.build_request_from_artifacts.return_value = StepRepairRequest(
        step_id="step_1__test_fn",
        step_intent="Click button",
        original_code="page.click('#btn')",
        error_classification=ErrorClassification(type="LOCATOR_NOT_FOUND"),
        error_details=ErrorDetails(message="Timeout"),
        artifacts=Artifacts(error_text="Timeout", dom_snapshot="<html></html>")
    )
    
    mock_repair_service = AsyncMock()
    mock_repair_service.repair_step.side_effect = StepNotRepairableError("Unable to repair")
    
    mock_patcher = MagicMock()
    
    orchestrator = SelfHealingExecutorOrchestrator(
        executor=mock_executor,
        repair_trigger=mock_trigger,
        repair_service=mock_repair_service,
        patcher=mock_patcher,
        config=config
    )
    
    # Mock explainer
    mock_explainer = AsyncMock()
    mock_explainer.generate_explanation.return_value = {
        "summary": "Element not found",
        "repaired": False
    }
    monkeypatch.setattr(orchestrator, "_explainer", mock_explainer)
    
    # Script path to execute
    script_file = tmp_path / "test.py"
    script_file.write_text("print('test')", encoding="utf-8")
    
    # Run execution with self-healing
    final_res = await orchestrator.execute_script_with_self_healing(script_path=str(script_file))
    
    # Verify it finalized as failed
    assert final_res.semantic_status == "failed"
    
    # Verify failed_runs directory contains execution files
    failed_run_dir = artifacts_root / "failed_runs" / run_id
    assert failed_run_dir.exists()
    assert (failed_run_dir / "status.txt").exists()
    assert (failed_run_dir / "final_script.py").exists()
    assert (failed_run_dir / "repair_report.json").exists()
    assert (failed_run_dir / "final_failure_explanation.json").exists()
    
    # Read final_failure_explanation.json and verify content
    explanation = json.loads((failed_run_dir / "final_failure_explanation.json").read_text(encoding="utf-8"))
    assert explanation["summary"] == "Element not found"


@pytest.mark.asyncio
async def test_cleanup_run_files_background_task(tmp_path):
    """Verifies that the cleanup_run_files background task deletes the response zip file and temporary run directories."""
    from app.routes.executor import cleanup_run_files
    
    # Create mock zip file
    zip_file = tmp_path / "run_123.zip"
    zip_file.write_text("zip content")
    
    # Create mock run directory
    run_dir = tmp_path / "runs" / "run_123"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "temp.txt").write_text("temp content")
    
    assert zip_file.exists()
    assert run_dir.exists()
    
    # Run cleanup
    await cleanup_run_files(zip_file, [str(run_dir)])
    
    # Verify deleted
    assert not zip_file.exists()
    assert not run_dir.exists()
