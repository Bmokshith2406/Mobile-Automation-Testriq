# app/middleware/rate_limit.py
"""
Rate Limiting Middleware

Dual-backend rate limiter:
- Redis backend: sliding-window per IP using sorted sets (multi-worker safe).
- In-memory backend: fallback for local dev / single-process deployments.

When REDIS_URL is set, Redis is used automatically.
"""

import time
import asyncio
from collections import defaultdict
from typing import Dict, Optional, Tuple
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import logging

logger = logging.getLogger("rate_limit")


# ---------------------------------------------------------------------------
# Redis sliding-window limiter (multi-worker safe)
# ---------------------------------------------------------------------------

_SLIDING_WINDOW_LUA = """
local key          = KEYS[1]
local now          = tonumber(ARGV[1])
local window_start = tonumber(ARGV[2])
local limit        = tonumber(ARGV[3])
local window_secs  = tonumber(ARGV[4])

redis.call('ZREMRANGEBYSCORE', key, 0, window_start)
local count = redis.call('ZCARD', key)

if count >= limit then
    return {1, 0, 0}
end

-- Use a random suffix to guarantee member uniqueness even if two requests
-- arrive within the same millisecond.
local member = tostring(now) .. '-' .. tostring(math.random(1, 1000000))
redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, window_secs + 1)

local oldest_score = 0
local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
if #oldest >= 2 then
    oldest_score = tonumber(oldest[2])
end

return {0, limit - count - 1, oldest_score}
"""


class _RedisRateLimiter:
    """
    Sliding-window rate limiter backed by Redis sorted sets.

    Uses an atomic Lua script — no race window between ZADD and ZCARD.
    Safe across multiple gunicorn workers sharing the same Redis instance.
    """

    def __init__(self, redis_client, requests_per_window: int, window_seconds: int):
        self._redis = redis_client
        self.requests_per_window = requests_per_window
        self.window_seconds = window_seconds
        self._script = self._redis.register_script(_SLIDING_WINDOW_LUA)

    async def check(self, client_ip: str) -> Tuple[bool, int, float]:
        """
        Returns (is_limited, remaining_requests, oldest_entry_timestamp).
        Increments the counter atomically if not limited.
        """
        key = f"rate_limit:{client_ip}"
        now = time.time()
        window_start = now - self.window_seconds

        result = await self._script(
            keys=[key],
            args=[now, window_start, self.requests_per_window, self.window_seconds],
        )

        is_limited = bool(result[0])
        remaining = int(result[1])
        oldest_score = float(result[2]) if result[2] else now

        return (is_limited, remaining, oldest_score)


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Token bucket rate limiter middleware.

    Limits requests per IP address within a sliding time window.
    Uses Redis when available, falls back to in-memory otherwise.
    """

    # Paths that bypass rate limiting entirely
    _EXEMPT_PATHS = frozenset({
        "/health", "/health/", "/metrics", "/metrics/",
        "/health/live", "/health/ready", "/health/deep",
    })

    def __init__(
        self,
        app,
        requests_per_window: int = 10,
        window_seconds: int = 60,
    ):
        super().__init__(app)
        self.requests_per_window = requests_per_window
        self.window_seconds = window_seconds

        # Try to initialise the Redis backend
        self._redis_limiter: Optional[_RedisRateLimiter] = None
        self._init_redis()

        # In-memory fallback
        self._requests: Dict[str, list] = defaultdict(list)
        self._lock = asyncio.Lock()
        self._last_cleanup = time.time()

        backend = "Redis" if self._redis_limiter else "in-memory"
        logger.info(
            "Rate limiter initialised | backend=%s | %d req / %ds",
            backend, requests_per_window, window_seconds,
        )

    def _init_redis(self) -> None:
        """Attempt to connect to Redis. Silently skip if unavailable."""
        try:
            from app.core.config import get_settings
            settings = get_settings()
            redis_url = getattr(settings, "REDIS_URL", None)
            if not redis_url:
                return

            import redis.asyncio as aioredis
            client = aioredis.from_url(redis_url, decode_responses=True)
            self._redis_limiter = _RedisRateLimiter(
                client,
                self.requests_per_window,
                self.window_seconds,
            )
            logger.info("Rate limiter: Redis backend active at %s", redis_url)
        except ImportError:
            logger.warning(
                "redis package not installed — rate limiter using in-memory backend"
            )
        except Exception as exc:
            logger.warning(
                "Redis unavailable for rate limiting (%s) — falling back to in-memory",
                exc,
            )

    # ------------------------------------------------------------------
    # In-memory fallback helpers
    # ------------------------------------------------------------------

    def _cleanup_stale_requests(self, now: float) -> None:
        window_start = now - self.window_seconds
        inactive_ips = []
        for ip, timestamps in list(self._requests.items()):
            active_ts = [ts for ts in timestamps if ts > window_start]
            if active_ts:
                self._requests[ip] = active_ts
            else:
                inactive_ips.append(ip)
        for ip in inactive_ips:
            self._requests.pop(ip, None)

    def _get_client_ip(self, request: Request) -> str:
        """Extract the real client IP, respecting proxy trust settings."""
        from app.core.config import get_settings
        settings = get_settings()
        if settings.TRUST_FORWARDED_IP:
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                return forwarded.split(",")[0].strip()
            real_ip = request.headers.get("x-real-ip")
            if real_ip:
                return real_ip
        return request.client.host if request.client else "unknown"

    async def _is_rate_limited(self, client_ip: str) -> Tuple[bool, int, float]:
        """
        In-memory sliding window check.
        Returns (is_limited, remaining_requests, oldest_entry_timestamp).
        """
        async with self._lock:
            now = time.time()
            window_start = now - self.window_seconds

            # Periodic global cleanup (every 10 minutes)
            if now - self._last_cleanup >= 600:
                self._cleanup_stale_requests(now)
                self._last_cleanup = now

            # Trim stale entries for this IP
            self._requests[client_ip] = [
                ts for ts in self._requests[client_ip]
                if ts > window_start
            ]

            timestamps = self._requests[client_ip]
            current_count = len(timestamps)
            oldest = timestamps[0] if timestamps else now

            if current_count >= self.requests_per_window:
                return (True, 0, oldest)

            timestamps.append(now)
            remaining = max(0, self.requests_per_window - current_count - 1)
            return (False, remaining, oldest)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def dispatch(self, request: Request, call_next):
        # Exempt health / metrics endpoints
        if request.url.path in self._EXEMPT_PATHS:
            return await call_next(request)

        client_ip = self._get_client_ip(request)

        # Choose backend
        if self._redis_limiter:
            try:
                is_limited, remaining, oldest_ts = await self._redis_limiter.check(client_ip)
            except Exception as exc:
                logger.warning(
                    "Redis rate-limit check failed (%s) — falling back to in-memory", exc
                )
                is_limited, remaining, oldest_ts = await self._is_rate_limited(client_ip)
        else:
            is_limited, remaining, oldest_ts = await self._is_rate_limited(client_ip)

        if is_limited:
            # Compute exact seconds until oldest entry expires — not the full window.
            import math
            reset_in = math.ceil(oldest_ts + self.window_seconds - time.time())
            reset_in = max(1, reset_in)

            logger.warning("Rate limit exceeded | ip=%s | retry_after=%ds", client_ip, reset_in)
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": "Rate limit exceeded",
                        "type": "RateLimitError",
                        "retry_after_seconds": reset_in,
                    }
                },
                headers={
                    "Retry-After": str(reset_in),
                    "X-RateLimit-Limit": str(self.requests_per_window),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(oldest_ts + self.window_seconds)),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.requests_per_window)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
