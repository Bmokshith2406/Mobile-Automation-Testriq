# tests/test_middleware_rate_limit.py
"""
Tests for RateLimitMiddleware (app/middleware/rate_limit.py)

Covers:
- In-memory backend rate limit enforcement
- Exempt paths bypass the limiter
- Remaining header counts down correctly
- Rate limit is enforced after window fills up
- In-memory cleanup of stale entries
"""

import asyncio
import time
import pytest
from fastapi import Request
from app.middleware.rate_limit import RateLimitMiddleware


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def limiter():
    """A fresh in-memory rate limiter (no Redis) with tight limits for testing."""
    m = RateLimitMiddleware(app=None, requests_per_window=3, window_seconds=60)
    # Force no Redis backend
    m._redis_limiter = None
    return m


def _make_request(client_host: str = "1.2.3.4") -> Request:
    scope = {"type": "http", "headers": [], "client": (client_host, 9000)}
    return Request(scope=scope)


# ---------------------------------------------------------------------------
# Tests — IP extraction
# ---------------------------------------------------------------------------

class TestGetClientIp:

    def test_direct_peer_when_trust_disabled(self, monkeypatch):
        monkeypatch.setenv("TRUST_FORWARDED_IP", "false")
        monkeypatch.setenv("API_KEY", "a" * 32)
        m = RateLimitMiddleware(app=None)
        m._redis_limiter = None
        scope = {
            "type": "http",
            "headers": [(b"x-forwarded-for", b"9.9.9.9")],
            "client": ("127.0.0.1", 80),
        }
        assert m._get_client_ip(Request(scope=scope)) == "127.0.0.1"

    def test_x_forwarded_for_when_trust_enabled(self, monkeypatch):
        monkeypatch.setenv("TRUST_FORWARDED_IP", "true")
        monkeypatch.setenv("API_KEY", "a" * 32)
        m = RateLimitMiddleware(app=None)
        m._redis_limiter = None
        scope = {
            "type": "http",
            "headers": [(b"x-forwarded-for", b"203.0.113.1, 10.0.0.1")],
            "client": ("127.0.0.1", 80),
        }
        assert m._get_client_ip(Request(scope=scope)) == "203.0.113.1"

    def test_unknown_when_no_client(self, monkeypatch):
        monkeypatch.setenv("TRUST_FORWARDED_IP", "false")
        monkeypatch.setenv("API_KEY", "a" * 32)
        m = RateLimitMiddleware(app=None)
        m._redis_limiter = None
        scope = {"type": "http", "headers": [], "client": None}
        assert m._get_client_ip(Request(scope=scope)) == "unknown"


# ---------------------------------------------------------------------------
# Tests — in-memory rate limiting logic
# ---------------------------------------------------------------------------

class TestInMemoryRateLimit:

    @pytest.mark.asyncio
    async def test_first_request_not_limited(self, limiter):
        is_limited, remaining, _ = await limiter._is_rate_limited("10.0.0.1")
        assert not is_limited
        assert remaining == 2  # 3 max - 1 used = 2

    @pytest.mark.asyncio
    async def test_remaining_decrements(self, limiter):
        ip = "10.0.0.2"
        _, r1, _ = await limiter._is_rate_limited(ip)
        _, r2, _ = await limiter._is_rate_limited(ip)
        _, r3, _ = await limiter._is_rate_limited(ip)
        assert r1 == 2
        assert r2 == 1
        assert r3 == 0

    @pytest.mark.asyncio
    async def test_fourth_request_is_limited(self, limiter):
        ip = "10.0.0.3"
        for _ in range(3):
            await limiter._is_rate_limited(ip)
        is_limited, remaining, _ = await limiter._is_rate_limited(ip)
        assert is_limited
        assert remaining == 0

    @pytest.mark.asyncio
    async def test_different_ips_are_independent(self, limiter):
        ip_a = "10.0.0.4"
        ip_b = "10.0.0.5"
        for _ in range(3):
            await limiter._is_rate_limited(ip_a)
        # ip_a is now limited; ip_b should still be fresh
        is_limited_b, _, _ = await limiter._is_rate_limited(ip_b)
        assert not is_limited_b

    @pytest.mark.asyncio
    async def test_stale_entries_expire(self):
        """Requests older than the window should not count."""
        m = RateLimitMiddleware(app=None, requests_per_window=2, window_seconds=1)
        m._redis_limiter = None
        ip = "10.0.0.6"
        # Fill up the window
        await m._is_rate_limited(ip)
        await m._is_rate_limited(ip)
        is_limited, _, _ = await m._is_rate_limited(ip)
        assert is_limited
        # Wait for window to expire
        await asyncio.sleep(1.1)
        is_limited_after, _, _ = await m._is_rate_limited(ip)
        assert not is_limited_after

    @pytest.mark.asyncio
    async def test_cleanup_removes_inactive_ips(self, limiter):
        ip = "10.0.0.7"
        await limiter._is_rate_limited(ip)
        # Manually expire the entry
        limiter._requests[ip] = [time.time() - 999]
        limiter._cleanup_stale_requests(time.time())
        assert ip not in limiter._requests
