import pytest
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_KEY = "a" * 32
_VALID_CORS = '["http://localhost:3000"]'


def _apply_env(monkeypatch, overrides: dict) -> None:
    """Set env vars for a Settings construction; uses valid defaults."""
    base = {
        "ENV": "development",
        "API_KEY": _VALID_KEY,
        "API_KEY_ENABLED": "true",
        "CORS_ORIGINS": _VALID_CORS,
        "LLM_PROVIDER": "gemini",
    }
    base.update(overrides)
    for k, v in base.items():
        monkeypatch.setenv(k, v)


def _get_settings():
    from app.core.config import get_settings
    return get_settings()


# ---------------------------------------------------------------------------
# API_KEY strength validation
# ---------------------------------------------------------------------------

class TestApiKeyValidation:

    def test_empty_api_key_rejected(self, monkeypatch):
        _apply_env(monkeypatch, {"API_KEY": ""})
        with pytest.raises(Exception):  # ValidationError or SettingsError
            _get_settings()

    def test_placeholder_super_secret_rejected(self, monkeypatch):
        _apply_env(monkeypatch, {"API_KEY": "super-secret-key"})
        with pytest.raises(Exception):
            _get_settings()

    def test_placeholder_automation_script_generator_rejected(self, monkeypatch):
        _apply_env(monkeypatch, {"API_KEY": "AutomationScriptGenerator"})
        with pytest.raises(Exception):
            _get_settings()

    def test_short_key_under_32_chars_rejected(self, monkeypatch):
        _apply_env(monkeypatch, {"API_KEY": "tooshort"})
        with pytest.raises(Exception):
            _get_settings()

    def test_exactly_32_chars_accepted(self, monkeypatch):
        key = "x" * 32
        _apply_env(monkeypatch, {"API_KEY": key})
        s = _get_settings()
        assert s.API_KEY == key

    def test_long_strong_key_accepted(self, monkeypatch):
        import secrets
        key = secrets.token_urlsafe(48)
        _apply_env(monkeypatch, {"API_KEY": key})
        s = _get_settings()
        assert s.API_KEY == key

    def test_api_key_check_skipped_when_disabled(self, monkeypatch):
        """When API_KEY_ENABLED=false the weak-key validator must NOT raise."""
        _apply_env(monkeypatch, {"API_KEY": "weak", "API_KEY_ENABLED": "false"})
        s = _get_settings()
        assert s.API_KEY_ENABLED is False


# ---------------------------------------------------------------------------
# CORS validation
# ---------------------------------------------------------------------------

class TestCorsValidation:

    def test_wildcard_blocked_in_production(self, monkeypatch):
        _apply_env(monkeypatch, {"ENV": "production", "CORS_ORIGINS": '["*"]'})
        with pytest.raises(Exception):
            _get_settings()

    def test_wildcard_allowed_in_development(self, monkeypatch):
        _apply_env(monkeypatch, {"ENV": "development", "CORS_ORIGINS": '["*"]'})
        s = _get_settings()
        assert "*" in s.CORS_ORIGINS

    def test_explicit_origin_accepted_in_production(self, monkeypatch):
        _apply_env(monkeypatch, {
            "ENV": "production",
            "CORS_ORIGINS": '["https://myapp.example.com"]',
        })
        s = _get_settings()
        assert "https://myapp.example.com" in s.CORS_ORIGINS

    def test_empty_cors_origins_default(self, monkeypatch):
        _apply_env(monkeypatch, {"CORS_ORIGINS": "[]"})
        s = _get_settings()
        assert s.CORS_ORIGINS == []

    def test_comma_separated_origins_parsed(self, monkeypatch):
        _apply_env(monkeypatch, {
            "CORS_ORIGINS": '["https://a.com","https://b.com"]',
        })
        s = _get_settings()
        assert "https://a.com" in s.CORS_ORIGINS
        assert "https://b.com" in s.CORS_ORIGINS


# ---------------------------------------------------------------------------
# LLM provider
# ---------------------------------------------------------------------------

class TestLlmProviderValidation:

    def test_gemini_accepted(self, monkeypatch):
        _apply_env(monkeypatch, {"LLM_PROVIDER": "gemini"})
        s = _get_settings()
        assert s.LLM_PROVIDER == "gemini"

    def test_openai_accepted(self, monkeypatch):
        _apply_env(monkeypatch, {"LLM_PROVIDER": "openai"})
        s = _get_settings()
        assert s.LLM_PROVIDER == "openai"

    def test_anthropic_rejected(self, monkeypatch):
        _apply_env(monkeypatch, {"LLM_PROVIDER": "anthropic"})
        with pytest.raises(Exception):
            _get_settings()

    def test_unknown_provider_rejected(self, monkeypatch):
        _apply_env(monkeypatch, {"LLM_PROVIDER": "cohere"})
        with pytest.raises(Exception):
            _get_settings()
