import pytest

from app.core.config import Settings, assert_valid_startup_settings
from app.core.errors import ProductionError
from app.core.validation import (
    validate_content_type,
    validate_html_content,
    validate_report_name,
)


def test_validate_content_type_accepts_charset_suffix():
    assert validate_content_type("text/html; charset=utf-8") == "text/html"


def test_validate_html_content_allows_script_tags_for_generated_reports():
    assert validate_html_content("<html><script>alert(1)</script></html>") is None


def test_validate_report_name_rejects_invalid_characters():
    with pytest.raises(ProductionError):
        validate_report_name("quarterly/report")


def test_reports_settings_accept_mongo_connection_string_alias(monkeypatch):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.setenv("MONGO_CONNECTION_STRING", "mongodb://example.test:27017")

    settings = Settings(_env_file=None)

    assert settings.MONGODB_URI == "mongodb://example.test:27017"


def test_reports_settings_require_explicit_mongodb_uri_when_enabled():
    settings = Settings(_env_file=None, MONGO_ENABLED=True, MONGODB_URI="", API_KEY="ReportsRAG")

    with pytest.raises(ValueError, match="MONGODB_URI is required"):
        assert_valid_startup_settings(settings)
