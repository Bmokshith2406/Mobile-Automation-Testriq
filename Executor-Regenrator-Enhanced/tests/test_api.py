"""
API Integration Tests

Tests for the FastAPI endpoints:
- Health checks
- Repair endpoint
- Executor endpoint
"""

import pytest
import json
from unittest.mock import patch, AsyncMock, MagicMock

from fastapi.testclient import TestClient


# ==================================================
# Health Check Tests
# ==================================================

class TestHealthEndpoints:
    """Tests for health check endpoints."""
    
    def test_basic_health_check(self, client: TestClient):
        """Test basic health endpoint returns OK."""
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert "env" in data
    
    def test_liveness_check(self, client: TestClient):
        """Test Kubernetes liveness probe."""
        response = client.get("/health/live")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["healthy", "unhealthy"]
        assert "checks" in data
    
    def test_readiness_check(self, client: TestClient):
        """Test Kubernetes readiness probe."""
        response = client.get("/health/ready")
        
        # May be 503 if LLM not configured, that's OK for test
        assert response.status_code in [200, 503]
        data = response.json()
        assert "status" in data
        assert "checks" in data
    
    def test_startup_check(self, client: TestClient):
        """Test Kubernetes startup probe."""
        response = client.get("/health/startup")
        
        assert response.status_code in [200, 503]
        data = response.json()
        assert "status" in data
    
    def test_deep_health_check(self, client: TestClient):
        """Test deep health check endpoint."""
        response = client.get("/health/deep")
        
        # Always returns 200 for monitoring
        assert response.status_code == 200
        data = response.json()
        assert "checks" in data
        assert "uptime_seconds" in data


# ==================================================
# Info Endpoint Tests
# ==================================================

class TestInfoEndpoint:
    """Tests for the info endpoint."""
    
    def test_info_endpoint(self, client: TestClient):
        """Test info endpoint returns app information."""
        response = client.get("/info")
        
        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "version" in data
        assert "features" in data


# ==================================================
# Repair Endpoint Tests
# ==================================================

class TestRepairEndpoint:
    """Tests for the repair API endpoint."""
    
    def test_repair_missing_payload(self, client: TestClient):
        """Test repair endpoint requires payload."""
        response = client.post("/repair")
        
        assert response.status_code == 422  # Validation error
    
    def test_repair_invalid_json(self, client: TestClient):
        """Test repair endpoint rejects invalid JSON."""
        response = client.post(
            "/repair",
            data={"payload": "not valid json"},
        )
        
        assert response.status_code == 400
        assert "Invalid JSON" in response.json()["detail"]
    
    def test_repair_invalid_payload_schema(self, client: TestClient):
        """Test repair endpoint validates payload schema."""
        response = client.post(
            "/repair",
            data={"payload": json.dumps({"invalid": "schema"})},
        )
        
        assert response.status_code == 400
    
    def test_repair_payload_too_large(self, client: TestClient):
        """Test repair endpoint rejects large payloads."""
        # Create a payload larger than 5MB
        large_payload = json.dumps({
            "step_id": "test",
            "step_intent": "test",
            "original_code": "x" * (6 * 1024 * 1024),  # 6MB
            "error_classification": {"type": "TEST"},
            "error_details": {"message": "test"},
        })
        
        response = client.post(
            "/repair",
            data={"payload": large_payload},
        )
        
        assert response.status_code == 413
    
    def test_repair_invalid_image_type(self, client: TestClient, sample_repair_request):
        """Test repair endpoint rejects invalid image payloads."""
        payload = sample_repair_request.model_dump_json()
        
        response = client.post(
            "/repair",
            data={"payload": payload},
            files={"error_image": ("test.gif", b"fake image", "image/gif")},
        )
        
        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid image file"
    
    def test_repair_invalid_png_signature(self, client: TestClient, sample_repair_request, invalid_png_bytes):
        """Test repair endpoint validates binary image signatures."""
        payload = sample_repair_request.model_dump_json()
        
        response = client.post(
            "/repair",
            data={"payload": payload},
            files={"error_image": ("test.png", invalid_png_bytes, "image/png")},
        )
        
        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid image file"
    
    @patch("app.routes.repair._REPAIR_SERVICE.repair_step", new_callable=AsyncMock)
    def test_repair_success(self, mock_repair_step, client: TestClient, sample_repair_request):
        """Test successful repair returns code."""
        mock_repair_step.return_value = ('await page.click("button.submit")', "click")
        
        payload = sample_repair_request.model_dump_json()
        
        response = client.post(
            "/repair",
            data={"payload": payload},
        )
        
        assert response.status_code == 200
        assert "await page.click" in response.text
        assert response.headers.get("X-Repair-Outcome") == "SUCCESS"
    
    @patch("app.routes.repair._REPAIR_SERVICE.repair_step", new_callable=AsyncMock)
    def test_repair_not_repairable(self, mock_repair_step, client: TestClient, sample_repair_request):
        """Test non-repairable step returns 409."""
        from app.core.exceptions import StepNotRepairableError
        mock_repair_step.side_effect = StepNotRepairableError("Cannot repair")
        
        payload = sample_repair_request.model_dump_json()
        
        response = client.post(
            "/repair",
            data={"payload": payload},
        )
        
        assert response.status_code == 409
        data = response.json()
        assert data["outcome"] == "NOT_REPAIRABLE"
        assert data["retryable"] is False
    
    @patch("app.routes.repair._REPAIR_SERVICE.repair_step", new_callable=AsyncMock)
    def test_repair_with_valid_png(self, mock_repair_step, client: TestClient, sample_repair_request, valid_png_bytes):
        """Test repair with valid PNG screenshot."""
        mock_repair_step.return_value = ('await page.click("button")', "click")
        
        payload = sample_repair_request.model_dump_json()
        
        response = client.post(
            "/repair",
            data={"payload": payload},
            files={"error_image": ("screenshot.png", valid_png_bytes, "image/png")},
        )
        
        assert response.status_code == 200

    @pytest.mark.parametrize(
        ("filename", "content_type", "fixture_name"),
        [
            ("screenshot.jpg", "image/jpeg", "valid_jpeg_bytes"),
            ("screenshot.webp", "image/webp", "valid_webp_bytes"),
        ],
    )
    @patch("app.routes.repair._REPAIR_SERVICE.repair_step", new_callable=AsyncMock)
    def test_repair_with_supported_non_png_images(
        self,
        mock_repair_step,
        client: TestClient,
        sample_repair_request,
        request,
        filename: str,
        content_type: str,
        fixture_name: str,
    ):
        """Test repair accepts JPEG and WebP screenshots."""
        mock_repair_step.return_value = ('await page.click("button")', "click")
        image_bytes = request.getfixturevalue(fixture_name)
        payload = sample_repair_request.model_dump_json()

        response = client.post(
            "/repair",
            data={"payload": payload},
            files={"error_image": (filename, image_bytes, content_type)},
        )

        assert response.status_code == 200


# ==================================================
# Executor Endpoint Tests
# ==================================================

class TestExecutorEndpoint:
    """Tests for the executor API endpoint."""

    def test_legacy_executor_routes_removed(self, client: TestClient):
        """Generic executor routes are no longer public API routes."""
        assert client.post("/executor").status_code in {404, 405}
        assert client.post("/executor/run").status_code in {404, 405}
    
    def test_executor_missing_file(self, client: TestClient):
        """Test executor requires a file."""
        response = client.post("/executor/playwright/run")
        
        assert response.status_code == 422
    
    def test_executor_non_python_file(self, client: TestClient):
        """Test executor rejects non-Python files."""
        response = client.post(
            "/executor/playwright/run",
            files={"script": ("test.txt", b"print('hello')", "text/plain")},
        )
        
        assert response.status_code == 400
        assert "Only .py files" in response.json()["detail"]
    
    @patch("app.routes.executor_routes.common._orchestrator")
    def test_executor_success(self, mock_orchestrator, client: TestClient):
        """Test successful script execution."""
        # Create a mock result
        mock_result = MagicMock()
        mock_result.semantic_status = "passed"
        mock_result.exit_code = 0
        mock_result.stdout = "Test passed"
        mock_result.stderr = ""
        mock_result.timed_out = False
        mock_result.run_id = "test123"
        
        import tempfile
        from pathlib import Path
        tmp_dir = tempfile.mkdtemp()
        mock_result.working_dir = tmp_dir
        
        # Create the successful_runs directory expected by the route
        run_dir_temp = Path(tmp_dir)
        project_root = run_dir_temp.parents[1]
        successful_runs_dir = project_root / "successful_runs"
        run_dir = successful_runs_dir / "test123"
        run_dir.mkdir(parents=True, exist_ok=True)
        
        mock_orchestrator.execute_script_with_self_healing = AsyncMock(return_value=mock_result)
        
        script_content = b"print('hello world')"
        
        response = client.post(
            "/executor/playwright/run",
            files={"script": ("test.py", script_content, "text/x-python")},
        )
        
        assert response.status_code == 200
        assert response.headers.get("X-Semantic-Status") == "passed"
        mock_orchestrator.execute_script_with_self_healing.assert_awaited_once()
        assert (
            mock_orchestrator.execute_script_with_self_healing.await_args.kwargs["framework_override"]
            == "playwright"
        )

    @pytest.mark.parametrize("framework", ["cypress", "appium"])
    @patch("app.routes.executor_routes.common._orchestrator")
    def test_framework_specific_routes_success(self, mock_orchestrator, client: TestClient, framework: str):
        """Test non-Playwright framework routes select their framework explicitly."""
        mock_result = MagicMock()
        mock_result.semantic_status = "passed"
        mock_result.exit_code = 0
        mock_result.stdout = "Test passed"
        mock_result.stderr = ""
        mock_result.timed_out = False
        mock_result.run_id = f"{framework}123"

        import tempfile
        from pathlib import Path
        tmp_dir = tempfile.mkdtemp()
        mock_result.working_dir = tmp_dir

        run_dir_temp = Path(tmp_dir)
        project_root = run_dir_temp.parents[1]
        run_dir = project_root / "successful_runs" / mock_result.run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        mock_orchestrator.execute_script_with_self_healing = AsyncMock(return_value=mock_result)

        script_content = (
            b"from appium import webdriver\nprint('hello')"
            if framework == "appium"
            else b"print('hello')"
        )
        response = client.post(
            f"/executor/{framework}/run",
            files={"script": ("test.py", script_content, "text/x-python")},
        )

        assert response.status_code == 200
        assert response.headers.get("X-Semantic-Status") == "passed"
        assert (
            mock_orchestrator.execute_script_with_self_healing.await_args.kwargs["framework_override"]
            == framework
        )
    
    @patch("app.routes.executor_routes.common._orchestrator")
    def test_executor_failed_script(self, mock_orchestrator, client: TestClient):
        """Test failed script execution."""
        mock_result = MagicMock()
        mock_result.semantic_status = "failed"
        mock_result.exit_code = 1
        mock_result.stdout = ""
        mock_result.stderr = "AssertionError"
        mock_result.timed_out = False
        mock_result.run_id = "test456"
        
        import tempfile
        tmp_dir = tempfile.mkdtemp()
        mock_result.working_dir = tmp_dir
        
        mock_orchestrator.execute_script_with_self_healing = AsyncMock(return_value=mock_result)
        
        response = client.post(
            "/executor/selenium/run",
            files={"script": ("test.py", b"assert False", "text/x-python")},
        )
        
        assert response.status_code == 200  # Returns 200 even for failed tests
        assert response.headers.get("X-Semantic-Status") == "failed"
        assert (
            mock_orchestrator.execute_script_with_self_healing.await_args.kwargs["framework_override"]
            == "selenium"
        )
        import io
        import zipfile

        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            assert "final_script.py" in archive.namelist()


# ==================================================
# Metrics Endpoint Tests
# ==================================================

class TestMetricsEndpoint:
    """Tests for metrics endpoint."""
    
    def test_metrics_disabled(self, client: TestClient):
        """Test metrics endpoint when disabled."""
        # Metrics are disabled in test environment
        response = client.get("/metrics")
        
        # Either 404 (disabled) or 200 (enabled)
        assert response.status_code in [200, 404]


# ==================================================
# Error Handling Tests
# ==================================================

class TestErrorHandling:
    """Tests for error handling."""
    
    def test_404_not_found(self, client: TestClient):
        """Test 404 for unknown routes."""
        response = client.get("/nonexistent")
        
        assert response.status_code == 404
    
    def test_method_not_allowed(self, client: TestClient):
        """Test 405 for wrong HTTP method."""
        response = client.get("/repair")
        
        assert response.status_code == 405
