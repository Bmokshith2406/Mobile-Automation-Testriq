"""
Unit tests for core services.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.models.cir import ActionType, CIRBlock, CIRAction
from app.models.step_repair import (
    StepRepairRequest,
    ErrorClassification,
    ErrorDetails,
    Artifacts,
)
from app.models.extraction import ExtractedLocator, ExtractedValue
from app.core.utils import (
    extract_quoted,
    extract_code_block,
    sanitize_selector,
    ExecutionStatus,
    RepairOutcome,
    ExtractionResult,
)


# =============================================================================
# Text Utility Tests
# =============================================================================

class TestExtractQuoted:
    """Tests for extract_quoted utility."""
    
    def test_extracts_double_quoted_string(self):
        result = extract_quoted('Click on "Submit Button"')
        assert result == "Submit Button"
    
    def test_extracts_first_quoted_string(self):
        result = extract_quoted('Click "First" then "Second"')
        assert result == "First"
    
    def test_returns_none_for_no_quotes(self):
        result = extract_quoted("No quotes here")
        assert result is None
    
    def test_handles_empty_quotes(self):
        result = extract_quoted('Empty ""')
        assert result == ""
    
    def test_handles_single_quotes_fallback(self):
        result = extract_quoted("Click on 'Submit'")
        assert result == "Submit"


class TestExtractCodeBlock:
    """Tests for extract_code_block utility."""
    
    def test_extracts_python_code_block(self):
        text = '''Here is the code:
```python
await page.click("#submit")
```
Done'''
        result = extract_code_block(text)
        assert result == 'await page.click("#submit")'
    
    def test_extracts_generic_code_block(self):
        text = '''```
await page.fill("#input", "test")
```'''
        result = extract_code_block(text)
        assert result == 'await page.fill("#input", "test")'
    
    def test_returns_original_if_no_block(self):
        text = 'await page.click("#btn")'
        result = extract_code_block(text)
        assert result == text
    
    def test_handles_multiline_code(self):
        text = '''```python
line1
line2
line3
```'''
        result = extract_code_block(text)
        assert "line1" in result
        assert "line2" in result
        assert "line3" in result


class TestSanitizeSelector:
    """Tests for sanitize_selector utility."""
    
    def test_removes_javascript_injection(self):
        selector = 'button[onclick="javascript:alert(1)"]'
        result = sanitize_selector(selector)
        assert "javascript:" not in result
    
    def test_preserves_valid_selector(self):
        selector = 'button.submit-btn[data-testid="submit"]'
        result = sanitize_selector(selector)
        assert result == selector
    
    def test_handles_text_selector(self):
        selector = 'text="Submit Form"'
        result = sanitize_selector(selector)
        assert result == selector


# =============================================================================
# Enum Tests
# =============================================================================

class TestExecutionStatus:
    """Tests for ExecutionStatus enum."""
    
    def test_status_values(self):
        assert ExecutionStatus.PASSED.value == "passed"
        assert ExecutionStatus.FAILED.value == "failed"
        assert ExecutionStatus.TIMEOUT.value == "timeout"
        assert ExecutionStatus.SKIPPED.value == "skipped"
    
    def test_is_terminal(self):
        assert ExecutionStatus.PASSED.is_terminal() is True
        assert ExecutionStatus.FAILED.is_terminal() is True
        assert ExecutionStatus.RUNNING.is_terminal() is False
        assert ExecutionStatus.PENDING.is_terminal() is False


class TestRepairOutcome:
    """Tests for RepairOutcome enum."""
    
    def test_outcome_values(self):
        assert RepairOutcome.SUCCESS.value == "success"
        assert RepairOutcome.PARTIAL.value == "partial"
        assert RepairOutcome.FAILURE.value == "failure"
    
    def test_is_success(self):
        assert RepairOutcome.SUCCESS.is_success() is True
        assert RepairOutcome.PARTIAL.is_success() is False
        assert RepairOutcome.FAILURE.is_success() is False


# =============================================================================
# Extraction Result Tests
# =============================================================================

class TestExtractionResult:
    """Tests for ExtractionResult dataclass."""
    
    def test_successful_extraction(self):
        locator = ExtractedLocator(strategy="css", value="#submit")
        result = ExtractionResult(
            locator=locator,
            value=None,
            confidence=0.95,
            source="llm"
        )
        assert result.is_successful() is True
        assert result.confidence == 0.95
    
    def test_failed_extraction(self):
        result = ExtractionResult(
            locator=None,
            value=None,
            confidence=0.0,
            source="fallback"
        )
        assert result.is_successful() is False
    
    def test_with_value(self):
        locator = ExtractedLocator(strategy="css", value="#input")
        value = ExtractedValue(text="test input", is_sensitive=False)
        result = ExtractionResult(
            locator=locator,
            value=value,
            confidence=0.9,
            source="llm"
        )
        assert result.locator is not None
        assert result.value is not None
        assert result.value.text == "test input"


# =============================================================================
# CIR Model Tests
# =============================================================================

class TestCIRBlock:
    """Tests for CIR block model."""
    
    def test_creates_valid_block(self):
        action = CIRAction(
            action_type=ActionType.click,
            locator='button:has-text("Submit")',
            description="Click submit button"
        )
        block = CIRBlock(
            step_id="test__step_1",
            intent="Submit the form",
            actions=[action]
        )
        assert block.step_id == "test__step_1"
        assert len(block.actions) == 1
        assert block.actions[0].action_type == ActionType.click
    
    def test_block_with_multiple_actions(self):
        actions = [
            CIRAction(
                action_type=ActionType.click,
                locator="#field",
                description="Focus field"
            ),
            CIRAction(
                action_type=ActionType.type,
                locator="#field",
                value="test",
                description="Type value"
            ),
        ]
        block = CIRBlock(
            step_id="test__step_2",
            intent="Fill form field",
            actions=actions
        )
        assert len(block.actions) == 2


class TestCIRAction:
    """Tests for CIR action model."""
    
    def test_click_action(self):
        action = CIRAction(
            action_type=ActionType.click,
            locator='text="Login"',
            description="Click login"
        )
        assert action.action_type == ActionType.click
        assert action.value is None
    
    def test_type_action(self):
        action = CIRAction(
            action_type=ActionType.type,
            locator="#username",
            value="testuser",
            description="Enter username"
        )
        assert action.action_type == ActionType.type
        assert action.value == "testuser"
    
    def test_select_action(self):
        action = CIRAction(
            action_type=ActionType.select,
            locator="#country",
            value="US",
            description="Select country"
        )
        assert action.action_type == ActionType.select


# =============================================================================
# Step Repair Request Tests
# =============================================================================

class TestStepRepairRequest:
    """Tests for step repair request model."""
    
    def test_valid_request(self):
        request = StepRepairRequest(
            step_id="test_login__step_1",
            step_intent="Click the login button",
            original_code='await page.click("#login")',
            error_classification=ErrorClassification(
                type="LOCATOR_NOT_FOUND",
                subtype="timeout"
            ),
            error_details=ErrorDetails(
                message="Timeout 5000ms exceeded",
                stack_trace="at click (/test.py:10)"
            ),
        )
        assert request.step_id == "test_login__step_1"
        assert request.error_classification.type == "LOCATOR_NOT_FOUND"
    
    def test_request_with_artifacts(self):
        request = StepRepairRequest(
            step_id="test__step_1",
            step_intent="Fill username",
            original_code='await page.fill("#user", "test")',
            error_classification=ErrorClassification(type="ELEMENT_NOT_VISIBLE"),
            error_details=ErrorDetails(message="Element not visible"),
            artifacts=Artifacts(
                dom_snapshot="<input id='username' type='text'>",
                page_url="http://localhost:3000",
            ),
        )
        assert request.artifacts is not None
        assert request.artifacts.dom_snapshot is not None


# =============================================================================
# Error Classification Tests
# =============================================================================

class TestErrorClassification:
    """Tests for error classification model."""
    
    def test_locator_not_found(self):
        classification = ErrorClassification(
            type="LOCATOR_NOT_FOUND",
            subtype="timeout",
            confidence=0.95
        )
        assert classification.type == "LOCATOR_NOT_FOUND"
        assert classification.confidence == 0.95
    
    def test_assertion_failed(self):
        classification = ErrorClassification(
            type="ASSERTION_FAILED",
            subtype="text_mismatch"
        )
        assert classification.type == "ASSERTION_FAILED"


# =============================================================================
# Integration Style Tests (with mocks)
# =============================================================================

class TestCIRBuilderIntegration:
    """Integration-style tests for CIR builder with mocked LLM."""
    
    @pytest.mark.asyncio
    async def test_builds_click_cir(self, mock_llm_executor, sample_repair_request):
        """Test building CIR for click action."""
        from app.services.cir_builder import CIRBuilder
        
        # Configure mock
        mock_llm_executor.run_classifier.return_value = "click"
        mock_llm_executor.run_extractor.return_value = 'click:text("Login")'
        
        builder = CIRBuilder()
        builder.classifier.llm = mock_llm_executor
        builder.click_extractor.llm = mock_llm_executor
        
        # Build CIR
        block, context = await builder.build(request=sample_repair_request)
        
        assert block is not None
        assert len(block.actions) >= 1
        assert block.actions[0].action_type == ActionType.click
    
    @pytest.mark.asyncio
    async def test_builds_type_cir(self, mock_llm_executor):
        """Test building CIR for type action."""
        from app.services.cir_builder import CIRBuilder
        
        request = StepRepairRequest(
            step_id="test__step_1",
            step_intent="Type username into the field",
            original_code='await page.fill("#user", "admin")',
            error_classification=ErrorClassification(type="LOCATOR_NOT_FOUND"),
            error_details=ErrorDetails(message="Timeout"),
        )
        
        mock_llm_executor.run_classifier.return_value = "type"
        mock_llm_executor.run_extractor.return_value = 'type:placeholder("username") value("username")'
        
        builder = CIRBuilder()
        builder.classifier.llm = mock_llm_executor
        builder.type_extractor.llm = mock_llm_executor
        
        block, context = await builder.build(request=request)
        
        assert block is not None
        # Should have focus + type actions
        assert any(a.action_type == ActionType.type for a in block.actions)


class TestStepCodeGeneratorIntegration:
    """Integration-style tests for code generator."""
    
    def test_generates_click_code(self, mock_llm_executor):
        """Test generating Playwright code for click action."""
        from app.services.generator import StepCodeGenerator
        
        action = CIRAction(
            action_type=ActionType.click,
            locator='button:has-text("Submit")',
            description="Click submit"
        )
        
        generator = StepCodeGenerator()
        code_lines = generator.generate(action)
        code = "\n".join(code_lines)
        
        assert code is not None
        assert "click" in code.lower() or "submit" in code.lower()
    
    def test_generates_type_code(self, mock_llm_executor):
        """Test generating Playwright code for type action."""
        from app.services.generator import StepCodeGenerator
        
        action = CIRAction(
            action_type=ActionType.type,
            locator="#username",
            value="testuser",
            description="Type username"
        )
        
        generator = StepCodeGenerator()
        code_lines = generator.generate(action)
        code = "\n".join(code_lines)
        
        assert code is not None
        assert "fill" in code.lower() or "type" in code.lower()


class TestStepVerifierIntegration:
    """Integration-style tests for step verifier."""

    @pytest.mark.asyncio
    async def test_verifies_valid_code(self, mock_llm_executor):
        """Test verification of syntactically correct code."""
        from app.services.step_verifier import StepVerifier

        mock_llm_executor.run_verifier_structured.return_value = (
            '{"verdict": "correct", "reason": "code correctly clicks the target"}'
        )

        verifier = StepVerifier()
        verifier.llm = mock_llm_executor

        code = 'await page.click("button#submit")'
        intent = "Click submit button"

        result = await verifier.verify(code, intent)

        assert result.passed is True

    @pytest.mark.asyncio
    async def test_rejects_invalid_code(self, mock_llm_executor):
        """Test rejection of invalid code."""
        from app.services.step_verifier import StepVerifier

        mock_llm_executor.run_verifier_structured.return_value = (
            '{"verdict": "incorrect", "reason": "wrong locator strategy used"}'
        )

        verifier = StepVerifier()
        verifier.llm = mock_llm_executor

        code = 'await page.click('  # Invalid syntax
        intent = "Click button"

        result = await verifier.verify(code, intent)

        assert result.passed is False


# =============================================================================
# Safety Module Tests
# =============================================================================

class TestCircuitBreaker:
    """Tests for circuit breaker pattern."""
    
    @pytest.mark.asyncio
    async def test_circuit_opens_after_failures(self):
        """Test that circuit opens after threshold failures."""
        from app.core.resilience import CircuitBreaker
        
        breaker = CircuitBreaker(
            failure_threshold=3,
            recovery_timeout=1.0,
            half_open_max=1
        )
        
        # Record failures
        for _ in range(3):
            breaker.record_failure()
        
        assert breaker.is_open() is True
    
    @pytest.mark.asyncio
    async def test_circuit_allows_when_closed(self):
        """Test that circuit allows calls when closed."""
        from app.core.resilience import CircuitBreaker
        
        breaker = CircuitBreaker(
            failure_threshold=3,
            recovery_timeout=1.0,
            half_open_max=1
        )
        
        assert breaker.is_open() is False
        breaker.record_success()
        assert breaker.is_open() is False


class TestBackoffPolicy:
    """Tests for backoff policy."""
    
    def test_exponential_backoff(self):
        """Test exponential backoff calculation."""
        from app.core.resilience import BackoffPolicy
        
        policy = BackoffPolicy(
            base_delay=1.0,
            max_delay=60.0,
            exponential_base=2.0,
            jitter=False
        )
        
        assert policy.get_delay(attempt=0) == 1.0
        assert policy.get_delay(attempt=1) == 2.0
        assert policy.get_delay(attempt=2) == 4.0
    
    def test_max_delay_cap(self):
        """Test that delay is capped at max."""
        from app.core.resilience import BackoffPolicy
        
        policy = BackoffPolicy(
            base_delay=1.0,
            max_delay=10.0,
            exponential_base=2.0,
            jitter=False
        )
        
        # 2^10 = 1024, should be capped at 10
        assert policy.get_delay(attempt=10) == 10.0


class TestFailureFingerprint:
    """Tests for failure fingerprinting."""
    
    def test_same_error_same_fingerprint(self):
        """Test that identical errors produce same fingerprint."""
        from app.core.utils import FailureFingerprint
        
        fp1 = FailureFingerprint.create(
            step_id="test__step_1",
            error_type="LOCATOR_NOT_FOUND",
            error_message="Timeout waiting for selector"
        )
        
        fp2 = FailureFingerprint.create(
            step_id="test__step_1",
            error_type="LOCATOR_NOT_FOUND",
            error_message="Timeout waiting for selector"
        )
        
        assert fp1 == fp2
    
    def test_different_errors_different_fingerprint(self):
        """Test that different errors produce different fingerprints."""
        from app.core.utils import FailureFingerprint
        
        fp1 = FailureFingerprint.create(
            step_id="test__step_1",
            error_type="LOCATOR_NOT_FOUND",
            error_message="Error 1"
        )
        
        fp2 = FailureFingerprint.create(
            step_id="test__step_1",
            error_type="ASSERTION_FAILED",
            error_message="Error 2"
        )
        
        assert fp1 != fp2


class TestScriptPatcher:
    """Tests for ScriptPatcher with call argument patching."""

    def test_patch_step_and_guarded_step_argument(self, tmp_path):
        from app.services.script_patcher import ScriptPatcher
        
        script_content = """# -*- coding: utf-8 -*-
import asyncio

async def _step_2_e35ecbfe67d3(page):
    await page.wait_for_selector("input[name='usernameee']", timeout=10000)
    await target.fill('john')

async def test_flow():
    # Execute steps
    await _guarded_step(page, _step_2_e35ecbfe67d3, '2__step_2_e35ecbfe67d3', 2, "await page.wait_for_selector(\\\"input[name='usernameee']\\\", timeout=10000)\\nawait target.fill('john')", "Enter username.", 1)
"""
        script_file = tmp_path / "test_script.py"
        script_file.write_text(script_content, encoding="utf-8")
        
        patcher = ScriptPatcher()
        new_body = "    await page.locator('#username').fill('admin')"
        
        patcher.patch_step(
            script_path=str(script_file),
            step_function_name="_step_2_e35ecbfe67d3",
            new_step_body=new_body,
            backup=False,
        )
        
        updated_content = script_file.read_text(encoding="utf-8")
        
        # Verify function body is updated
        assert 'await page.locator(\'#username\').fill(\'admin\')' in updated_content
        # Verify function body old lines are gone
        assert 'await page.wait_for_selector("input[name=\'usernameee\']", timeout=10000)' not in updated_content
        
        # Verify the 5th argument of the _guarded_step call is patched
        assert "await _guarded_step(page, _step_2_e35ecbfe67d3, '2__step_2_e35ecbfe67d3', 2, \"    await page.locator('#username').fill('admin')\"" in updated_content

    def test_patch_sync_appium_step_and_guarded_step_argument(self, tmp_path):
        from app.services.script_patcher import ScriptPatcher

        script_content = """from appium.webdriver.common.appiumby import AppiumBy

def _step_0_abc123(driver):
    element = driver.find_element(AppiumBy.ACCESSIBILITY_ID, 'Loginn')
    element.click()

def test_flow():
    _guarded_step(driver, _step_0_abc123, '0__step_0_abc123', 0, "element = driver.find_element(AppiumBy.ACCESSIBILITY_ID, 'Loginn')\\nelement.click()", "Tap Login.", 1, artifacts_dir, success_dir, step_metrics, running_summary_path)
"""
        script_file = tmp_path / "appium_script.py"
        script_file.write_text(script_content, encoding="utf-8")

        patcher = ScriptPatcher()
        new_body = "element = driver.find_element(AppiumBy.ACCESSIBILITY_ID, 'Login')\nelement.click()"

        patcher.patch_step(
            script_path=str(script_file),
            step_function_name="_step_0_abc123",
            new_step_body=new_body,
            backup=False,
        )

        updated_content = script_file.read_text(encoding="utf-8")

        assert "def _step_0_abc123(driver):" in updated_content
        assert "AppiumBy.ACCESSIBILITY_ID, 'Login'" in updated_content
        assert "AppiumBy.ACCESSIBILITY_ID, 'Loginn'" not in updated_content
        assert repr(new_body) in updated_content

    def test_patch_appium_matrix_device_specific_step_only(self, tmp_path):
        from app.services.script_patcher import ScriptPatcher

        script_content = """from appium.webdriver.common.appiumby import AppiumBy

def _step_0_android_hash_pixel_7(driver):
    element = driver.find_element(AppiumBy.ACCESSIBILITY_ID, 'Login')
    element.click()

def _step_1_ios_hash_iphone_latest(driver):
    element = driver.find_element(AppiumBy.ACCESSIBILITY_ID, 'Loginn')
    element.click()

def test_flow():
    if device_slug == 'pixel_7':
        _guarded_step(driver, _step_0_android_hash_pixel_7, '0_pixel_7__step_0_android_hash_pixel_7', 0, "element = driver.find_element(AppiumBy.ACCESSIBILITY_ID, 'Login')\\nelement.click()", "Tap Login.", 1, artifacts_dir, success_dir, step_metrics, running_summary_path, device_context)
    elif device_slug == 'iphone_latest':
        _guarded_step(driver, _step_1_ios_hash_iphone_latest, '0_iphone_latest__step_1_ios_hash_iphone_latest', 0, "element = driver.find_element(AppiumBy.ACCESSIBILITY_ID, 'Loginn')\\nelement.click()", "Tap Login.", 1, artifacts_dir, success_dir, step_metrics, running_summary_path, device_context)
"""
        script_file = tmp_path / "appium_matrix_script.py"
        script_file.write_text(script_content, encoding="utf-8")

        patcher = ScriptPatcher()
        new_body = "element = driver.find_element(AppiumBy.ACCESSIBILITY_ID, 'Login')\nelement.click()"

        patcher.patch_step(
            script_path=str(script_file),
            step_function_name="step_1_ios_hash_iphone_latest",
            new_step_body=new_body,
            backup=False,
        )

        updated_content = script_file.read_text(encoding="utf-8")

        assert "def _step_0_android_hash_pixel_7(driver):" in updated_content
        assert "def _step_1_ios_hash_iphone_latest(driver):" in updated_content
        assert "'0_pixel_7__step_0_android_hash_pixel_7'" in updated_content
        assert "'0_iphone_latest__step_1_ios_hash_iphone_latest'" in updated_content
        assert updated_content.count("AppiumBy.ACCESSIBILITY_ID, 'Loginn'") == 0
        assert (
            "_guarded_step(driver, _step_1_ios_hash_iphone_latest"
            in updated_content
        )
        assert repr(new_body) in updated_content


class TestFrameworkClassifier:
    """Tests for FrameworkClassifier service."""
    
    @pytest.mark.asyncio
    async def test_classify_by_heuristics(self):
        from app.services.framework_classifier import FrameworkClassifier
        import tempfile
        from pathlib import Path
        
        classifier = FrameworkClassifier()
        
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w", encoding="utf-8") as f:
            f.write("import playwright\nawait page.goto('http://example.com')")
            f_path = f.name
            
        try:
            res = await classifier.classify_framework(f_path)
            assert res == "playwright"
        finally:
            Path(f_path).unlink()
            
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w", encoding="utf-8") as f:
            f.write("from selenium import webdriver\ndriver.get('http://example.com')")
            f_path = f.name
            
        try:
            res = await classifier.classify_framework(f_path)
            assert res == "selenium"
        finally:
            Path(f_path).unlink()

        with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w", encoding="utf-8") as f:
            f.write("from appium import webdriver\nfrom appium.webdriver.common.appiumby import AppiumBy\ndriver = webdriver.Remote('http://34.46.45.187:4723/wd/hub')")
            f_path = f.name

        try:
            res = await classifier.classify_framework(f_path)
            assert res == "appium"
        finally:
            Path(f_path).unlink()
            
    @pytest.mark.asyncio
    async def test_classify_fallback_to_llm(self, mock_llm_executor):
        from app.services.framework_classifier import FrameworkClassifier
        import tempfile
        from pathlib import Path
        
        classifier = FrameworkClassifier()
        # Mock LLM response
        mock_llm_executor.run_classifier.return_value = "cypress"
        classifier._llm = mock_llm_executor
        
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w", encoding="utf-8") as f:
            f.write("# ambiguous script with no explicit imports\nprint('hello')")
            f_path = f.name
            
        try:
            res = await classifier.classify_framework(f_path)
            assert res == "cypress"
        finally:
            Path(f_path).unlink()


class TestStepVerifierFrameworkParam:
    """Test framework propagation inside step verifier."""

    @pytest.mark.asyncio
    async def test_verifies_with_framework_param(self, mock_llm_executor):
        """Test verification propagating framework to prompt builder."""
        from app.services.step_verifier import StepVerifier

        mock_llm_executor.run_verifier_structured.return_value = (
            '{"verdict": "correct", "reason": "code passes"}'
        )

        verifier = StepVerifier()
        verifier.llm = mock_llm_executor

        code = 'driver.find_element(By.ID, "submit").click()'
        intent = "Click submit button"

        result = await verifier.verify(code, intent, framework="selenium")
        assert result.passed is True


class TestStepVerifierStructuredOutput:
    """Tests for StepVerifier structured output parsing (Gemini schema-enforced JSON)."""

    @pytest.mark.asyncio
    async def test_parses_correct_verdict(self, mock_llm_executor):
        from app.services.step_verifier import StepVerifier

        mock_llm_executor.run_verifier_structured.return_value = (
            '{"verdict": "correct", "reason": "The code correctly targets the element"}'
        )

        verifier = StepVerifier()
        verifier.llm = mock_llm_executor

        result = await verifier.verify("page.click()", "Click element")
        assert result.passed is True
        assert result.get("verdict") == "correct"
        assert "correctly" in result.get("reason", "")

    @pytest.mark.asyncio
    async def test_parses_incorrect_verdict(self, mock_llm_executor):
        from app.services.step_verifier import StepVerifier

        mock_llm_executor.run_verifier_structured.return_value = (
            '{"verdict": "incorrect", "reason": "Wrong locator strategy used"}'
        )

        verifier = StepVerifier()
        verifier.llm = mock_llm_executor

        result = await verifier.verify("page.click()", "Click element")
        assert result.passed is False
        assert result.get("verdict") == "incorrect"
        assert "locator" in result.get("reason", "").lower()

    @pytest.mark.asyncio
    async def test_handles_none_response(self, mock_llm_executor):
        from app.services.step_verifier import StepVerifier

        mock_llm_executor.run_verifier_structured.return_value = None

        verifier = StepVerifier()
        verifier.llm = mock_llm_executor

        result = await verifier.verify("page.click()", "Click element")
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_handles_malformed_json(self, mock_llm_executor):
        from app.services.step_verifier import StepVerifier

        mock_llm_executor.run_verifier_structured.return_value = "not valid json at all"

        verifier = StepVerifier()
        verifier.llm = mock_llm_executor

        result = await verifier.verify("page.click()", "Click element")
        assert result.passed is False
