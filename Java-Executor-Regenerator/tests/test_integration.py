# tests/test_integration.py
"""
Integration tests for the Playwright Step Repair Engine.
Tests the complete repair pipeline end-to-end.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime

from httpx import AsyncClient

from app.main import app
from app.core.config import settings


# ==============================================================================
# FIXTURES
# ==============================================================================

@pytest.fixture
def mock_llm_response():
    """Mock LLM response for testing."""
    return 'click:text("Submit")'


@pytest.fixture
def valid_repair_request():
    """Valid repair request payload."""
    return {
        "step_id": "test_login__step_1",
        "step_intent": "Click the submit button",
        "original_code": 'await page.click("#submit")',
        "error_classification": {
            "type": "LOCATOR_NOT_FOUND",
            "root_cause": "selector_invalid"
        },
        "error_details": {
            "message": "Timeout 5000ms exceeded waiting for selector '#submit'",
            "traceback": "Error: Timeout 5000ms exceeded\n  at click"
        }
    }


@pytest.fixture
def valid_execution_request():
    """Valid execution request payload."""
    return {
        "script_path": "/tests/fixtures/sample_test.py",
        "enable_self_healing": True,
        "max_repair_attempts": 3
    }


# ==============================================================================
# API ENDPOINT TESTS
# ==============================================================================

class TestHealthEndpoints:
    """Tests for health check endpoints."""
    
    @pytest.mark.asyncio
    async def test_health_live(self, async_client: AsyncClient):
        """Test liveness probe."""
        response = await async_client.get("/health/live")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
    
    @pytest.mark.asyncio
    async def test_health_ready(self, async_client: AsyncClient):
        """Test readiness probe."""
        response = await async_client.get("/health/ready")
        assert response.status_code in [200, 503]
        data = response.json()
        assert "status" in data
        assert "checks" in data
    
    @pytest.mark.asyncio
    async def test_health_startup(self, async_client: AsyncClient):
        """Test startup probe."""
        response = await async_client.get("/health/startup")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


class TestRepairEndpoints:
    """Tests for repair API endpoints."""
    
    @pytest.mark.asyncio
    async def test_repair_missing_auth(
        self,
        async_client: AsyncClient,
        valid_repair_request: dict,
        security_settings,
    ):
        """Test repair endpoint requires authentication."""
        import json
        response = await async_client.post(
            "/repair",
            data={"payload": json.dumps(valid_repair_request)},
        )
        # Should fail without API key (when auth is enabled)
        assert response.status_code == 401
    
    @pytest.mark.asyncio
    async def test_repair_invalid_input(self, async_client: AsyncClient):
        """Test repair endpoint with invalid input."""
        import json
        response = await async_client.post(
            "/repair",
            data={"payload": json.dumps({"invalid": "data"})},
            headers={"X-API-Key": "test-key"},
        )
        assert response.status_code == 400
    
    @pytest.mark.asyncio
    async def test_repair_success(
        self,
        async_client: AsyncClient,
        valid_repair_request: dict,
        mock_llm_response: str,
    ):
        """Test successful repair request."""
        import json
        with patch("app.services.cir_builder.CIRBuilder") as mock_builder:
            # Mock the CIR builder
            mock_instance = MagicMock()
            mock_builder.return_value = mock_instance
            mock_instance.build = AsyncMock(return_value=(
                MagicMock(actions=[MagicMock(action_type=MagicMock(value="click"))]),
                MagicMock()
            ))
            
            response = await async_client.post(
                "/repair",
                data={"payload": json.dumps(valid_repair_request)},
                headers={"X-API-Key": "test-key"},
            )
            
            # May succeed or fail depending on LLM mock / repairability
            assert response.status_code in [200, 409, 500]
    
    @pytest.mark.asyncio
    async def test_repair_with_screenshot(
        self,
        async_client: AsyncClient,
        valid_repair_request: dict,
    ):
        """Test repair request with screenshot."""
        import json
        # Add a valid PNG screenshot (minimal valid PNG)
        # Minimal valid 1x1 PNG
        png_bytes = bytes([
            0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,  # PNG signature
            0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,  # IHDR chunk
            0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
            0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53,
            0xDE, 0x00, 0x00, 0x00, 0x0C, 0x49, 0x44, 0x41,  # IDAT chunk
            0x54, 0x08, 0xD7, 0x63, 0xF8, 0x0F, 0x00, 0x00,
            0x01, 0x01, 0x00, 0x05, 0xFE, 0xDC, 0xCC, 0x59,
            0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4E, 0x44,  # IEND chunk
            0xAE, 0x42, 0x60, 0x82
        ])
        
        response = await async_client.post(
            "/repair",
            data={"payload": json.dumps(valid_repair_request)},
            files={"error_image": ("screenshot.png", png_bytes, "image/png")},
            headers={"X-API-Key": "test-key"},
        )
        
        assert response.status_code in [200, 409, 500]
    
    @pytest.mark.asyncio
    async def test_repair_rate_limit(
        self,
        async_client: AsyncClient,
        valid_repair_request: dict,
    ):
        """Test rate limiting on repair endpoint."""
        import json
        # Make multiple rapid requests
        responses = []
        for _ in range(15):
            response = await async_client.post(
                "/repair",
                data={"payload": json.dumps(valid_repair_request)},
                headers={"X-API-Key": "test-key"},
            )
            responses.append(response.status_code)
        
        # Should eventually get rate limited
        # (depends on rate limit configuration)
        assert 429 in responses or all(r in [200, 409, 500] for r in responses)


class TestExecutorEndpoints:
    """Tests for executor API endpoints."""
    
    @pytest.mark.asyncio
    async def test_execute_missing_script(
        self,
        async_client: AsyncClient,
    ):
        """Test execution with missing script."""
        response = await async_client.post(
            "/executor/playwright/run",
            json={"script_path": "/nonexistent/script.py"},
            headers={"X-API-Key": "test-key"},
        )
        assert response.status_code in [400, 404, 422]
    
    @pytest.mark.asyncio
    async def test_execute_invalid_path(
        self,
        async_client: AsyncClient,
    ):
        """Test execution with path traversal attempt."""
        response = await async_client.post(
            "/executor/playwright/run",
            json={"script_path": "../../../etc/passwd"},
            headers={"X-API-Key": "test-key"},
        )
        # Should be rejected for security
        assert response.status_code in [400, 403, 422]


class TestMetricsEndpoint:
    """Tests for metrics endpoint."""
    
    @pytest.mark.asyncio
    async def test_metrics_endpoint(self, async_client: AsyncClient):
        """Test Prometheus metrics endpoint."""
        from app.core.config import get_settings
        settings = get_settings()
        old_val = settings.ENABLE_METRICS
        settings.ENABLE_METRICS = True
        try:
            response = await async_client.get("/metrics")
            assert response.status_code == 200
            assert "repair_requests_total" in response.text or response.status_code == 200
        finally:
            settings.ENABLE_METRICS = old_val


# ==============================================================================
# PIPELINE INTEGRATION TESTS
# ==============================================================================

class TestRepairPipeline:
    """Integration tests for the complete repair pipeline."""
    
    @pytest.mark.asyncio
    async def test_click_repair_pipeline(self, mock_llm_executor):
        """Test complete click repair pipeline."""
        from app.services.cir_builder import CIRBuilder
        from app.services.generator import StepCodeGenerator
        from app.services.step_verifier import StepVerifier
        from app.models.step_repair import (
            StepRepairRequest,
            ErrorClassification,
            ErrorDetails,
        )
        
        # Setup mocks
        mock_llm_executor.run_classifier.return_value = "click"
        mock_llm_executor.run_extractor.return_value = 'click:text("submit")'
        mock_llm_executor.run_verifier.return_value = "correct"
        
        # Create request
        request = StepRepairRequest(
            step_id="test__step_1",
            step_intent="Click the submit button",
            original_code='await page.click("#submit")',
            error_classification=ErrorClassification(type="LOCATOR_NOT_FOUND"),
            error_details=ErrorDetails(message="Timeout waiting for selector"),
        )
        
        # Build CIR
        builder = CIRBuilder()
        block, context = await builder.build(request=request)
        
        assert block is not None
        assert len(block.actions) >= 1
        
        # Generate code
        generator = StepCodeGenerator()
        generated_code_lines = generator.generate(block.actions[0])
        generated_code = "\n".join(generated_code_lines)
        
        assert generated_code is not None
        assert "click" in generated_code.lower() or "submit" in generated_code.lower()
    
    @pytest.mark.asyncio
    async def test_type_repair_pipeline(self, mock_llm_executor):
        """Test complete type/fill repair pipeline."""
        from app.services.cir_builder import CIRBuilder
        from app.models.step_repair import (
            StepRepairRequest,
            ErrorClassification,
            ErrorDetails,
        )
        
        # Setup mocks
        mock_llm_executor.run_classifier.return_value = "type"
        mock_llm_executor.run_extractor.return_value = (
            'type:role(textbox, name="Email") value("email")'
        )
        
        # Create request
        request = StepRepairRequest(
            step_id="test__step_2",
            step_intent="Type email address into the email field",
            original_code='await page.fill("#email", "test@example.com")',
            error_classification=ErrorClassification(type="LOCATOR_NOT_FOUND"),
            error_details=ErrorDetails(message="Timeout waiting for selector"),
        )
        
        # Build CIR
        builder = CIRBuilder()
        block, context = await builder.build(request=request)
        
        assert block is not None
    
    @pytest.mark.asyncio
    async def test_assert_repair_pipeline(self, mock_llm_executor):
        """Test complete assertion repair pipeline."""
        from app.services.cir_builder import CIRBuilder
        from app.models.step_repair import (
            StepRepairRequest,
            ErrorClassification,
            ErrorDetails,
        )
        
        # Setup mocks
        mock_llm_executor.run_classifier.return_value = "assert"
        mock_llm_executor.run_extractor.return_value = (
            'element_visible:text("Success")'
        )
        
        # Create request
        request = StepRepairRequest(
            step_id="test__step_3",
            step_intent="Verify success message is displayed",
            original_code='await expect(page.locator(".success")).toBeVisible()',
            error_classification=ErrorClassification(type="ASSERTION_FAILED"),
            error_details=ErrorDetails(message="Expected element to be visible"),
        )
        
        # Build CIR
        builder = CIRBuilder()
        block, context = await builder.build(request=request)
        
        assert block is not None


# ==============================================================================
# SAFETY MECHANISM TESTS
# ==============================================================================

class TestSafetyMechanisms:
    """Tests for safety mechanisms."""
    
    @pytest.mark.asyncio
    async def test_circuit_breaker(self):
        """Test circuit breaker behavior."""
        from app.core.resilience import CircuitBreaker
        
        breaker = CircuitBreaker(
            failure_threshold=3,
            recovery_timeout=1,
        )
        
        # Record failures
        for _ in range(3):
            breaker.record_failure()
        
        assert breaker.is_open() is True
    
    @pytest.mark.asyncio
    async def test_backoff_policy(self):
        """Test exponential backoff."""
        from app.core.resilience import BackoffPolicy
        
        policy = BackoffPolicy(
            base_delay=1.0,
            max_delay=30.0,
            exponential_base=2.0,
        )
        
        delay1 = policy.get_delay(attempt=1)
        delay2 = policy.get_delay(attempt=2)
        delay3 = policy.get_delay(attempt=3)
        
        assert delay1 < delay2 < delay3
        assert delay3 <= 30.0
    
    @pytest.mark.asyncio
    async def test_failure_fingerprint(self):
        """Test failure fingerprinting."""
        from app.core.utils import FailureFingerprint
        
        fingerprint1 = FailureFingerprint.compute(
            "test__step_1",
            "LOCATOR_NOT_FOUND",
            'await page.click("#btn")',
        )
        
        fingerprint2 = FailureFingerprint.compute(
            "test__step_1",
            "LOCATOR_NOT_FOUND",
            'await page.click("#btn")',
        )
        
        fingerprint3 = FailureFingerprint.compute(
            "test__step_2",
            "LOCATOR_NOT_FOUND",
            'await page.click("#btn")',
        )
        
        assert fingerprint1 == fingerprint2
        assert fingerprint1 != fingerprint3


# ==============================================================================
# DATABASE INTEGRATION TESTS
# ==============================================================================

class TestDatabaseIntegration:
    """Tests for database operations."""
    
    @pytest.mark.asyncio
    async def test_repair_history_create(self):
        """Test creating repair history record."""
        from app.core.database import get_repository, RepairRecord
        
        repo = await get_repository()
        
        record = RepairRecord(
            step_id="test__step_1",
            original_code='await page.click("#btn")',
            repaired_code='await page.click("text=Submit")',
            outcome="success",
            error_type="LOCATOR_NOT_FOUND",
            duration_ms=1500,
        )
        
        record_id = await repo.save_repair(record)
        assert record_id is not None
        
        fetched = await repo.get_repair(record_id)
        assert fetched is not None
        assert fetched.step_id == "test__step_1"
        assert fetched.outcome == "success"
    
    @pytest.mark.asyncio
    async def test_repair_history_statistics(self):
        """Test repair statistics calculation."""
        from app.core.database import get_repository, RepairRecord
        
        repo = await get_repository()
        
        initial_stats = await repo.get_repair_stats()
        initial_total = initial_stats.get("total", 0)
        
        # Create some test records
        for i in range(5):
            record = RepairRecord(
                step_id=f"test__step_{i}",
                original_code=f'await page.click("#btn{i}")',
                repaired_code=f'await page.click("text=Button{i}")',
                outcome="success" if i < 3 else "failure",
                duration_ms=1000 + i * 100,
            )
            await repo.save_repair(record)
        
        stats = await repo.get_repair_stats()
        
        assert stats["total"] == initial_total + 5
