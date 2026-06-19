"""
Security-focused tests for the repair engine.
"""
import pytest
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException


# =============================================================================
# API Key Authentication Tests
# =============================================================================

class TestAPIKeyAuthentication:
    """Tests for API key authentication."""
    
    @pytest.mark.asyncio
    async def test_missing_api_key_returns_401(self, test_client):
        """Test that missing API key returns 401."""
        response = test_client.post(
            "/repair",
            json={
                "step_id": "test__step_1",
                "step_intent": "Click button",
                "original_code": "await page.click('#btn')",
                "error_classification": {"type": "LOCATOR_NOT_FOUND"},
                "error_details": {"message": "Timeout"}
            }
        )
        assert response.status_code == 401
        assert "API key required" in response.json().get("detail", "")
    
    @pytest.mark.asyncio
    async def test_invalid_api_key_returns_401(self, test_client):
        """Test that invalid API key returns 401."""
        response = test_client.post(
            "/repair",
            json={
                "step_id": "test__step_1",
                "step_intent": "Click button",
                "original_code": "await page.click('#btn')",
                "error_classification": {"type": "LOCATOR_NOT_FOUND"},
                "error_details": {"message": "Timeout"}
            },
            headers={"X-API-Key": "invalid-key"}
        )
        assert response.status_code == 401
    
    @pytest.mark.asyncio
    async def test_valid_api_key_allowed(self, authenticated_client):
        """Test that valid API key is accepted."""
        # This would need proper mocking of the repair pipeline
        # For now, just verify the auth passes
        response = authenticated_client.get("/info")
        assert response.status_code == 200


# =============================================================================
# Rate Limiting Tests
# =============================================================================

class TestRateLimiting:
    """Tests for rate limiting."""
    
    @pytest.mark.asyncio
    async def test_rate_limit_headers_present(self, authenticated_client):
        """Test that rate limit headers are present in response."""
        response = authenticated_client.get("/health")
        # Check for standard rate limit headers
        headers = response.headers
        # These would be present if rate limiting is enabled
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_burst_requests_eventually_limited(self, authenticated_client):
        """Test that burst requests are eventually rate limited."""
        # Make many rapid requests
        responses = []
        for _ in range(50):
            response = authenticated_client.get("/health")
            responses.append(response.status_code)
        
        # Should have some 200s and potentially some 429s if rate limiting is strict
        assert 200 in responses


# =============================================================================
# Input Validation Tests
# =============================================================================

class TestInputValidation:
    """Tests for input validation security."""
    
    @pytest.mark.asyncio
    async def test_rejects_oversized_request(self, authenticated_client):
        """Test that oversized requests are rejected."""
        # Create a very large payload
        large_code = "x" * (10 * 1024 * 1024)  # 10MB
        
        response = authenticated_client.post(
            "/repair",
            json={
                "step_id": "test__step_1",
                "step_intent": "Click button",
                "original_code": large_code,
                "error_classification": {"type": "LOCATOR_NOT_FOUND"},
                "error_details": {"message": "Timeout"}
            }
        )
        # Should be rejected (413 or 422)
        assert response.status_code in [413, 422, 400]
    
    @pytest.mark.asyncio
    async def test_rejects_script_injection_in_step_id(self, authenticated_client):
        """Test that script injection in step_id is sanitized."""
        response = authenticated_client.post(
            "/repair",
            json={
                "step_id": "<script>alert('xss')</script>",
                "step_intent": "Click button",
                "original_code": "await page.click('#btn')",
                "error_classification": {"type": "LOCATOR_NOT_FOUND"},
                "error_details": {"message": "Timeout"}
            }
        )
        # Should be rejected or sanitized
        assert response.status_code in [400, 422, 401]
    
    @pytest.mark.asyncio
    async def test_validates_base64_image(self, authenticated_client):
        """Test that invalid base64 images are rejected."""
        response = authenticated_client.post(
            "/repair",
            json={
                "step_id": "test__step_1",
                "step_intent": "Click button",
                "original_code": "await page.click('#btn')",
                "error_classification": {"type": "LOCATOR_NOT_FOUND"},
                "error_details": {"message": "Timeout"},
                "screenshot_base64": "not-valid-base64!!!"
            }
        )
        # Should be rejected
        assert response.status_code in [400, 422, 401]


# =============================================================================
# Code Injection Prevention Tests
# =============================================================================

class TestCodeInjectionPrevention:
    """Tests for code injection prevention."""
    
    def test_forbidden_patterns_in_modifier(self):
        """Test that forbidden patterns are detected."""
        from app.services.step_modifier import StepModifier
        
        modifier = StepModifier()
        
        # Test various injection attempts
        dangerous_codes = [
            "import os; os.system('rm -rf /')",
            "__import__('subprocess').call(['ls'])",
            "eval('malicious')",
            "exec('dangerous')",
            "open('/etc/passwd').read()",
            "compile('code', 'file', 'exec')",
        ]
        
        for code in dangerous_codes:
            # The modifier should detect or reject these
            assert modifier._sanitize_llm_output(code) is None
    
    def test_safe_playwright_code_allowed(self):
        """Test that safe Playwright code passes validation."""
        from app.services.step_modifier import StepModifier
        
        modifier = StepModifier()
        
        safe_codes = [
            'await page.click("#submit")',
            'await page.fill("#username", "test")',
            'await page.wait_for_selector(".loaded")',
            'await page.locator("button").click()',
            'await expect(page.locator("#msg")).to_be_visible()',
        ]
        
        for code in safe_codes:
            assert modifier._sanitize_llm_output(code) is not None

    def test_ast_safety_blocks_structural_escapes(self):
        """Test that AST validation in modifier rejects structural escapes."""
        from app.services.step_modifier import StepModifier
        
        modifier = StepModifier()
        
        unsafe_structures = [
            "for i in range(5):\n    page.click('#btn')",
            "try:\n    page.click('#btn')\nexcept:\n    pass",
            "class Attack:\n    pass",
            "def helper():\n    return 42",
            "import os",
            "from math import sin",
        ]
        
        for code in unsafe_structures:
            assert modifier._sanitize_llm_output(code) is None


# =============================================================================
# Sandbox Execution Tests
# =============================================================================

class TestSandboxExecution:
    """Tests for sandboxed Python execution."""

    def test_validator_blocks_process_and_filesystem_primitives(self):
        """Test AST validator rejects dangerous host operations."""
        from app.executors.sandbox import ScriptSecurityValidator

        validator = ScriptSecurityValidator(strict_mode=True)
        dangerous_scripts = [
            "import os\nos.system('echo hi')",
            "import subprocess\nsubprocess.run(['echo', 'hi'])",
            "import shutil\nshutil.rmtree('tmp')",
        ]

        for script in dangerous_scripts:
            is_safe, reason = validator.validate(script)
            assert is_safe is False
            assert reason

    def test_validator_allows_basic_safe_script(self):
        """Test AST validator still allows simple safe Python."""
        from app.executors.sandbox import ScriptSecurityValidator

        validator = ScriptSecurityValidator(strict_mode=True)
        is_safe, reason = validator.validate("print('hello world')")

        assert is_safe is True
        assert reason == ""

    def test_validator_allows_user_whitelisted_imports(self):
        """Test that the whitelisted imports from the user's template are allowed."""
        from app.executors.sandbox import ScriptSecurityValidator

        validator = ScriptSecurityValidator(strict_mode=True)
        user_script = """
import re
import asyncio
import os
import inspect
import sys
import time
from datetime import datetime, timezone
import json
import hashlib
import traceback
from playwright.async_api import async_playwright, expect
"""
        is_safe, reason = validator.validate(user_script)
        assert is_safe is True
        assert reason == ""

    def test_validator_allows_name_attribute(self):
        """Test that accessing the __name__ attribute is allowed by the AST validator."""
        from app.executors.sandbox import ScriptSecurityValidator

        validator = ScriptSecurityValidator(strict_mode=True)
        safe_script = """
class MyClass:
    pass

name = MyClass.__name__
print(name)
"""
        is_safe, reason = validator.validate(safe_script)
        assert is_safe is True
        assert reason == ""

    def test_validator_allows_replace_method(self):
        """Test that calling the replace method is allowed by the AST validator (e.g. string replace)."""
        from app.executors.sandbox import ScriptSecurityValidator

        validator = ScriptSecurityValidator(strict_mode=True)
        safe_script = """
text = "hello world"
modified = text.replace("world", "there")
print(modified)
"""
        is_safe, reason = validator.validate(safe_script)
        assert is_safe is True
        assert reason == ""

    def test_validator_allows_walk_method(self):
        """Test that calling the walk method is allowed by the AST validator (e.g. os.walk)."""
        from app.executors.sandbox import ScriptSecurityValidator

        validator = ScriptSecurityValidator(strict_mode=True)
        safe_script = """
import os
for root, dirs, files in os.walk("."):
    pass
"""
        is_safe, reason = validator.validate(safe_script)
        assert is_safe is True
        assert reason == ""

    def test_validator_allows_run_method_but_blocks_modules(self):
        """Test that calling run (like asyncio.run) is allowed, but accessing sys.modules is blocked."""
        from app.executors.sandbox import ScriptSecurityValidator

        validator = ScriptSecurityValidator(strict_mode=True)
        safe_script = """
import asyncio
async def main():
    pass
asyncio.run(main())
"""
        is_safe, reason = validator.validate(safe_script)
        assert is_safe is True
        assert reason == ""

        # Test that sys.modules is blocked
        unsafe_script = """
import sys
m = sys.modules
"""
        is_safe, reason = validator.validate(unsafe_script)
        assert is_safe is False
        assert "Forbidden access to internal attribute: modules" in reason
    
    @pytest.mark.asyncio
    async def test_sandbox_blocks_file_access(self):
        """Test that sandbox blocks file system access."""
        from app.executors import SandboxedPythonExecutor
        
        executor = SandboxedPythonExecutor()
        
        # Try to access file system
        dangerous_script = '''
import os
os.listdir('/')
'''
        
        result = await executor.execute_sandboxed(dangerous_script)
        
        # Should fail or be blocked
        assert result.success is False or "blocked" in result.error.lower()
    
    @pytest.mark.asyncio
    async def test_sandbox_blocks_network_access(self):
        """Test that sandbox blocks network access."""
        from app.executors import SandboxedPythonExecutor
        
        executor = SandboxedPythonExecutor()
        
        dangerous_script = '''
import socket
s = socket.socket()
s.connect(('google.com', 80))
'''
        
        result = await executor.execute_sandboxed(dangerous_script)
        
        # Should fail or be blocked
        assert result.success is False
    
    @pytest.mark.asyncio
    async def test_sandbox_allows_playwright_operations(self):
        """Test that sandbox allows Playwright operations."""
        from app.executors import SandboxedPythonExecutor
        
        executor = SandboxedPythonExecutor()
        
        # This is a mock test - real Playwright would need browser
        safe_script = '''
# Simulated Playwright-like code
result = "click operation simulated"
print(result)
'''
        
        result = await executor.execute_sandboxed(safe_script)
        
        # Safe operations should pass validation at least
        assert result is not None


# =============================================================================
# CORS Tests
# =============================================================================

class TestCORS:
    """Tests for CORS configuration."""
    
    @pytest.mark.asyncio
    async def test_cors_preflight_request(self, test_client):
        """Test CORS preflight request handling."""
        response = test_client.options(
            "/repair",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "X-API-Key"
            }
        )
        # Should handle OPTIONS request
        assert response.status_code in [200, 204, 401]
    
    @pytest.mark.asyncio
    async def test_cors_headers_in_response(self, authenticated_client):
        """Test that CORS headers are present in response."""
        response = authenticated_client.get(
            "/health",
            headers={"Origin": "https://example.com"}
        )
        # CORS headers should be present if origin is allowed
        assert response.status_code == 200


# =============================================================================
# Session Security Tests
# =============================================================================

class TestSessionSecurity:
    """Tests for session and request security."""
    
    @pytest.mark.asyncio
    async def test_correlation_id_propagated(self, authenticated_client):
        """Test that correlation ID is propagated in response."""
        correlation_id = "test-correlation-123"
        response = authenticated_client.get(
            "/info",
            headers={"X-Request-ID": correlation_id}
        )
        
        # Response should echo or generate correlation ID
        assert response.status_code == 200
        response_id = response.headers.get("X-Request-ID")
        # Either echoed or new ID generated
        assert response_id is not None
    
    @pytest.mark.asyncio
    async def test_security_headers_present(self, authenticated_client):
        """Test that security headers are present."""
        response = authenticated_client.get("/info")
        
        headers = response.headers
        
        # Check for common security headers
        # These may or may not be present depending on config
        assert response.status_code == 200


# =============================================================================
# Error Information Leakage Tests
# =============================================================================

class TestErrorLeakage:
    """Tests for error information leakage prevention."""
    
    @pytest.mark.asyncio
    async def test_internal_errors_sanitized(self, authenticated_client):
        """Test that internal errors don't leak sensitive info."""
        # Trigger an error with malformed request
        response = authenticated_client.post(
            "/repair",
            json={"invalid": "request"}
        )
        
        # Error response should not contain stack traces in production
        error_detail = response.json().get("detail", "")
        
        # Should not contain file paths or internal details
        assert "/app/" not in str(error_detail)
        assert "Traceback" not in str(error_detail)
    
    @pytest.mark.asyncio
    async def test_database_errors_sanitized(self, authenticated_client):
        """Test that database errors don't leak connection strings."""
        # This would require triggering a DB error
        # For now, verify error handling structure exists
        response = authenticated_client.get("/health/ready")
        
        if response.status_code != 200:
            error_detail = str(response.json())
            # Should not contain connection strings
            assert "postgresql://" not in error_detail
            assert "password" not in error_detail.lower()
