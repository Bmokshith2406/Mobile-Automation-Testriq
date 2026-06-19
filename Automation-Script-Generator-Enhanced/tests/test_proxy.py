# tests/test_proxy.py
"""
Tests for RateLimitMiddleware._get_client_ip()

Uses monkeypatch.setenv + cache_clear (via conftest.py autouse fixture)
instead of directly mutating the shared Settings singleton, which is fragile
and may corrupt state across parallel tests.
"""

import pytest
from fastapi import Request
from app.middleware.rate_limit import RateLimitMiddleware


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request(forwarded_for: str | None = None, real_ip: str | None = None, client_host: str = "127.0.0.1") -> Request:
    """Build a minimal Starlette Request with the given headers and client."""
    headers = []
    if forwarded_for:
        headers.append((b"x-forwarded-for", forwarded_for.encode()))
    if real_ip:
        headers.append((b"x-real-ip", real_ip.encode()))
    scope = {
        "type": "http",
        "headers": headers,
        "client": (client_host, 12345),
    }
    return Request(scope=scope)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGetClientIp:

    def test_ignores_forwarded_headers_when_trust_disabled(self, monkeypatch):
        """When TRUST_FORWARDED_IP=false, always use the direct peer IP."""
        monkeypatch.setenv("TRUST_FORWARDED_IP", "false")
        monkeypatch.setenv("API_KEY", "a" * 32)
        monkeypatch.setenv("CORS_ORIGINS", '["http://localhost:3000"]')

        middleware = RateLimitMiddleware(app=None)
        req = _make_request(forwarded_for="203.0.113.195", real_ip="203.0.113.196")
        assert middleware._get_client_ip(req) == "127.0.0.1"

    def test_uses_x_forwarded_for_when_trust_enabled(self, monkeypatch):
        """When TRUST_FORWARDED_IP=true, return the first IP in X-Forwarded-For."""
        monkeypatch.setenv("TRUST_FORWARDED_IP", "true")
        monkeypatch.setenv("API_KEY", "a" * 32)
        monkeypatch.setenv("CORS_ORIGINS", '["http://localhost:3000"]')

        middleware = RateLimitMiddleware(app=None)
        req = _make_request(forwarded_for="203.0.113.195, 10.0.0.1")
        assert middleware._get_client_ip(req) == "203.0.113.195"

    def test_falls_back_to_x_real_ip_when_no_forwarded_for(self, monkeypatch):
        """When TRUST_FORWARDED_IP=true but X-Forwarded-For absent, use X-Real-IP."""
        monkeypatch.setenv("TRUST_FORWARDED_IP", "true")
        monkeypatch.setenv("API_KEY", "a" * 32)
        monkeypatch.setenv("CORS_ORIGINS", '["http://localhost:3000"]')

        middleware = RateLimitMiddleware(app=None)
        req = _make_request(real_ip="203.0.113.196")
        assert middleware._get_client_ip(req) == "203.0.113.196"

    def test_returns_unknown_for_no_client(self, monkeypatch):
        """When request.client is None and no proxy headers, return 'unknown'."""
        monkeypatch.setenv("TRUST_FORWARDED_IP", "false")
        monkeypatch.setenv("API_KEY", "a" * 32)
        monkeypatch.setenv("CORS_ORIGINS", '["http://localhost:3000"]')

        middleware = RateLimitMiddleware(app=None)
        scope = {"type": "http", "headers": [], "client": None}
        req = Request(scope=scope)
        assert middleware._get_client_ip(req) == "unknown"
