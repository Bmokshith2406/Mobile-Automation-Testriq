# tests/conftest.py
"""
Shared pytest fixtures and configuration.

Key responsibilities:
- Set a valid API_KEY environment variable BEFORE any app module is
  imported, so that the Settings validator does not raise at collection
  time when the real .env contains a weak/missing key.
- Auto-clear the @lru_cache on get_settings() between tests so that
  monkeypatch.setenv() changes are actually picked up by the app code.
- Provide reusable fixtures (test client, valid headers, sample payloads).
"""

import os

# -------------------------------------------------------------------------
# Inject a strong test API_KEY before ANY app module is imported.
# This must happen at module-scope (not inside a fixture) so it takes effect
# during pytest's collection phase when modules are first imported.
# -------------------------------------------------------------------------
_TEST_API_KEY = "a" * 32  # 32 chars, not in the blocklist

if not os.environ.get("API_KEY") or len(os.environ.get("API_KEY", "")) < 32:
    os.environ["API_KEY"] = _TEST_API_KEY

# CORS_ORIGINS must be valid JSON for pydantic-settings to parse list[str]
if not os.environ.get("CORS_ORIGINS"):
    os.environ["CORS_ORIGINS"] = '["http://localhost:3000"]'

import pytest
from app.core.config import get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache():
    """
    Clears the cached Settings instance before and after every test.

    Without this, the first test that imports get_settings() locks in the
    env-var values for all subsequent tests, making monkeypatch.setenv()
    calls ineffective.
    """
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
