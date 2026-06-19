"""
Pytest Configuration and Fixtures

Provides shared test fixtures for:
- FastAPI test client
- Mock LLM executor
- Mock services
- Database fixtures
- Configuration overrides
"""

import os
import pytest
import pytest_asyncio
import asyncio
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock, patch

# Set test environment before importing app modules
os.environ["ENV"] = "development"
os.environ["GOOGLE_API_KEY"] = "test-api-key"
os.environ["ENABLE_API_AUTH"] = "false"
os.environ["ENABLE_RATE_LIMITING"] = "false"
os.environ["ENABLE_METRICS"] = "false"
os.environ["ENABLE_TRACING"] = "false"
os.environ["MONGODB_URL"] = ""
os.environ["REDIS_URL"] = ""
os.environ["CELERY_BROKER_URL"] = ""
os.environ["CELERY_RESULT_BACKEND"] = ""

from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.config import Settings, get_settings, clear_settings_cache
from app.core.llm_executor import LLMExecutor
from app.core.database import InMemoryRepository, DatabaseManager
from app.models.step_repair import (
    StepRepairRequest,
    ErrorClassification,
    ErrorDetails,
    Artifacts,
)
from app.models.cir import (
    CIRBlock,
    CIRAction,
    ActionType,
    CIRBlockType,
    CIRLocator,
    LocatorStrategy,
)
from app.models.context import StepRepairContext


# ==================================================
# Event Loop Configuration
# ==================================================

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# ==================================================
# Configuration Fixtures
# ==================================================

@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset singleton instances between tests."""
    # Clear settings cache
    clear_settings_cache()
    
    # Reset LLMExecutor singleton
    LLMExecutor._instance = None
    LLMExecutor._semaphore = None
    
    # Reset DatabaseManager singleton
    DatabaseManager._instance = None
    
    yield


@pytest.fixture
def test_settings() -> Settings:
    """Provide test settings."""
    return Settings(
        ENV="development",
        GOOGLE_API_KEY="test-api-key",
        ENABLE_API_AUTH=False,
        ENABLE_RATE_LIMITING=False,
        ENABLE_METRICS=False,
        ENABLE_TRACING=False,
        ENABLE_MULTIMODAL=True,
        ENABLE_SELF_HEALING=True,
        DRY_RUN_MODE=False,
        LLM_TIMEOUT_SECONDS=10,
        LLM_MAX_CONCURRENT_CALLS=2,
    )


@pytest.fixture
def mock_settings(test_settings):
    """Mock get_settings to return test settings."""
    with patch("app.core.config.get_settings", return_value=test_settings):
        yield test_settings


# ==================================================
# HTTP Client Fixtures
# ==================================================

@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """Provide a synchronous test client."""
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """Provide an async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def security_settings() -> Generator[None, None, None]:
    """Override environment variables for API authentication tests."""
    old_env = dict(os.environ)
    
    os.environ["ENABLE_API_AUTH"] = "true"
    os.environ["ALLOWED_API_KEYS"] = '["test-key"]'
    os.environ["API_SECRET_KEY"] = "test-secret-key"
    os.environ["ENABLE_RATE_LIMITING"] = "false"
    os.environ["ENABLE_METRICS"] = "false"
    os.environ["ENABLE_TRACING"] = "false"
    os.environ["CORS_ORIGINS"] = '["https://example.com","http://localhost:3000"]'
    
    clear_settings_cache()
    yield
    
    # Restore env
    for k in list(os.environ.keys()):
        if k not in old_env:
            del os.environ[k]
    os.environ.update(old_env)
    clear_settings_cache()


@pytest.fixture
def test_client(security_settings) -> Generator[TestClient, None, None]:
    """Provide a sync test client with API authentication enabled."""
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def authenticated_client(security_settings) -> Generator[TestClient, None, None]:
    """Provide an authenticated sync test client with API authentication enabled."""
    with TestClient(app, raise_server_exceptions=False) as client:
        client.headers["X-API-Key"] = "test-key"
        yield client


# ==================================================
# LLM Mock Fixtures
# ==================================================

@pytest.fixture(autouse=True)
def mock_llm_executor(reset_singletons, monkeypatch):
    """Provide a mock LLM executor."""
    executor = AsyncMock(spec=LLMExecutor)
    
    # Default return values
    executor.run_classifier.return_value = "click"
    executor.run_extractor.return_value = 'click:text("Submit")'
    executor.run_verifier.return_value = "correct"
    executor.run_modifier.return_value = 'await page.click("button.submit")'
    executor.run_multimodal_classifier.return_value = "click"
    executor.run_multimodal_extractor.return_value = 'click:text("Submit")'

    # Structured output defaults (return schema-valid JSON strings)
    executor.run_verifier_structured.return_value = (
        '{"verdict": "correct", "reason": "verified by mock"}'
    )
    _repair_json = (
        '{"failure_reason": "locator changed", "repair_action": "updated selector",'
        ' "why_previous_failed": "old locator not found in DOM",'
        ' "why_repair_was_selected": "new locator matches DOM element",'
        ' "rerun_result": "pending_rerun", "execution_passed": null,'
        ' "failure_type": "LOCATOR_CHANGE", "summary": "Updated locator to match DOM"}'
    )
    executor.run_modifier_structured.return_value = _repair_json
    executor.run_multimodal_modifier_structured.return_value = _repair_json
    
    monkeypatch.setattr(LLMExecutor, "_instance", executor)
    
    return executor


@pytest.fixture
def mock_llm_responses():
    """Provide configurable mock LLM responses."""
    class MockResponses:
        def __init__(self):
            self.classifier = "click"
            self.extractor = 'click:text("Submit")'
            self.verifier = "correct"
            self.modifier = 'await page.click("button.submit")'
        
        def set_classifier(self, value: str):
            self.classifier = value
            return self
        
        def set_extractor(self, value: str):
            self.extractor = value
            return self
        
        def set_verifier(self, value: str):
            self.verifier = value
            return self
        
        def set_modifier(self, value: str):
            self.modifier = value
            return self
    
    return MockResponses()


# ==================================================
# Database Fixtures
# ==================================================

@pytest.fixture
def memory_repository():
    """Provide an in-memory repository for testing."""
    return InMemoryRepository(max_records=100)


@pytest_asyncio.fixture
async def async_repository():
    """Provide an async-compatible repository."""
    repo = InMemoryRepository(max_records=100)
    return repo


# ==================================================
# Model Fixtures
# ==================================================

@pytest.fixture
def sample_repair_request() -> StepRepairRequest:
    """Provide a sample step repair request."""
    return StepRepairRequest(
        step_id="test__login__step_1",
        step_intent="Click the login button",
        original_code='await page.click("#login-btn")',
        error_classification=ErrorClassification(type="LOCATOR_NOT_FOUND"),
        error_details=ErrorDetails(
            message="Timeout 5000ms exceeded waiting for selector '#login-btn'",
            failed_api="page.click",
        ),
        traceback="Error: Timeout 5000ms exceeded...",
        artifacts=Artifacts(
            dom_snapshot="<html><body><button class='btn-login'>Login</button></body></html>",
            page_url="https://example.com/login",
        ),
    )


@pytest.fixture
def sample_repair_request_type() -> StepRepairRequest:
    """Provide a sample type action repair request."""
    return StepRepairRequest(
        step_id="test__form__step_2",
        step_intent="Type email address in the email field",
        original_code='await page.type("#email", "test@example.com")',
        error_classification=ErrorClassification(type="LOCATOR_NOT_FOUND"),
        error_details=ErrorDetails(
            message="Timeout waiting for selector '#email'",
            failed_api="page.type",
        ),
        artifacts=Artifacts(
            dom_snapshot='<input type="email" name="email" placeholder="Enter email">',
            page_url="https://example.com/signup",
        ),
    )


@pytest.fixture
def sample_repair_request_assert() -> StepRepairRequest:
    """Provide a sample assertion repair request."""
    return StepRepairRequest(
        step_id="test__verify__step_3",
        step_intent="Verify success message is displayed",
        original_code='await expect(page.locator("#success")).to_be_visible()',
        error_classification=ErrorClassification(type="ASSERTION_FAILED"),
        error_details=ErrorDetails(
            message="Locator resolved to hidden element",
            failed_api="expect.to_be_visible",
        ),
        artifacts=Artifacts(
            dom_snapshot='<div class="alert success">Operation completed!</div>',
            page_url="https://example.com/result",
        ),
    )


@pytest.fixture
def sample_cir_block() -> CIRBlock:
    """Provide a sample CIR block."""
    return CIRBlock(
        block_id="block_1",
        intent="Click the submit button",
        block_type=CIRBlockType.step,
        actions=[
            CIRAction(
                action_type=ActionType.click,
                target=CIRLocator(
                    locator_strategy=LocatorStrategy.text,
                    locator_value="Submit",
                ),
            ),
        ],
    )


@pytest.fixture
def sample_context() -> StepRepairContext:
    """Provide a sample repair context."""
    return StepRepairContext(
        reference_code='await page.click("#submit")',
        matched_script="test_login.py",
    )


# ==================================================
# PNG Test Data
# ==================================================

@pytest.fixture
def valid_png_bytes() -> bytes:
    """Provide valid minimal PNG bytes for testing."""
    # Minimal valid 1x1 transparent PNG
    return (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
        b'\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89'
        b'\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01'
        b'\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
    )


@pytest.fixture
def invalid_png_bytes() -> bytes:
    """Provide invalid PNG bytes for testing."""
    return b"not a png file"


@pytest.fixture
def valid_jpeg_bytes() -> bytes:
    """Provide valid-enough JPEG signature bytes for upload validation tests."""
    return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"


@pytest.fixture
def valid_webp_bytes() -> bytes:
    """Provide valid-enough WebP signature bytes for upload validation tests."""
    return b"RIFF\x16\x00\x00\x00WEBPVP8 \x0a\x00\x00\x00"


# ==================================================
# Service Mock Fixtures
# ==================================================

@pytest.fixture
def mock_cir_builder(sample_cir_block, sample_context):
    """Provide a mock CIR builder."""
    builder = AsyncMock()
    builder.build.return_value = (sample_cir_block, sample_context)
    return builder


@pytest.fixture
def mock_generator():
    """Provide a mock code generator."""
    generator = MagicMock()
    generator.generate.return_value = ['await page.click("button.submit")']
    return generator


@pytest.fixture
def mock_verifier():
    """Provide a mock step verifier."""
    verifier = AsyncMock()
    verifier.verify.return_value = {"verdict": "correct", "reason": None}
    return verifier


@pytest.fixture
def mock_modifier():
    """Provide a mock step modifier."""
    modifier = AsyncMock()
    modifier.modify.return_value = 'await page.click("button.submit")'
    return modifier


# ==================================================
# Helper Functions
# ==================================================

def create_repair_request(
    step_id: str = "test__step_1",
    intent: str = "Test action",
    original_code: str = 'await page.click("#btn")',
    error_type: str = "LOCATOR_NOT_FOUND",
    error_message: str = "Element not found",
) -> StepRepairRequest:
    """Helper to create repair requests with custom values."""
    return StepRepairRequest(
        step_id=step_id,
        step_intent=intent,
        original_code=original_code,
        error_classification=ErrorClassification(type=error_type),
        error_details=ErrorDetails(message=error_message),
    )


def create_cir_action(
    action_type: ActionType,
    locator_strategy: LocatorStrategy = LocatorStrategy.text,
    locator_value: str = "Button",
    value: str = None,
) -> CIRAction:
    """Helper to create CIR actions."""
    return CIRAction(
        action_type=action_type,
        target=CIRLocator(
            locator_strategy=locator_strategy,
            locator_value=locator_value,
        ),
        value=value,
    )
