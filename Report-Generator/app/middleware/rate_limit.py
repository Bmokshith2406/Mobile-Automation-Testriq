import asyncio
import time
from collections import defaultdict, deque
from typing import Deque, DefaultDict, Optional

from fastapi import Request

from app.core.config import get_settings
from app.core.errors import APIException, ErrorCategory, ErrorCode, ErrorSeverity
from app.core.logger import get_logger


settings = get_settings()
logger = get_logger(__name__)


class RateLimiter:
    """Sliding-window rate limiter with optional Redis backing."""

    def __init__(self, requests_per_minute: int = 30):
        self.requests_per_minute = requests_per_minute
        self.window_seconds = 60
        self.backend = settings.RATE_LIMIT_BACKEND
        self._lock = asyncio.Lock()
        self._requests: DefaultDict[str, Deque[float]] = defaultdict(deque)
        self._redis = None

    async def initialize(self) -> None:
        if self.backend != "redis":
            return

        redis_url = settings.REDIS_URL.get_secret_value().strip() if settings.REDIS_URL else ""
        if not redis_url:
            logger.warning("RATE_LIMIT_BACKEND=redis configured without REDIS_URL; falling back to memory")
            self.backend = "memory"
            return

        try:
            from redis.asyncio import Redis

            self._redis = Redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
            await self._redis.ping()
            logger.info("Redis-backed rate limiter initialized")
        except Exception as exc:
            logger.warning(
                "Failed to initialize Redis-backed rate limiter; falling back to memory",
                extra={"error": str(exc)},
            )
            self.backend = "memory"
            self._redis = None

    async def shutdown(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def check_rate_limit(self, request: Request) -> None:
        client_key = self._get_client_key(request)
        now = time.time()

        if self.backend == "redis" and self._redis is not None:
            allowed, retry_after = await self._check_redis_limit(client_key, now)
        else:
            allowed, retry_after = await self._check_memory_limit(client_key, now)

        if not allowed:
            raise APIException(
                error_code=ErrorCode.RATE_LIMIT_EXCEEDED,
                message="Rate limit exceeded",
                status_code=429,
                category=ErrorCategory.RATE_LIMIT,
                severity=ErrorSeverity.WARNING,
                retryable=True,
                details={"retry_after_seconds": retry_after},
                headers={"Retry-After": str(retry_after)},
            )

    async def _check_memory_limit(self, client_key: str, now: float) -> tuple[bool, int]:
        async with self._lock:
            window = self._requests[client_key]
            cutoff = now - self.window_seconds

            while window and window[0] <= cutoff:
                window.popleft()

            if len(window) >= self.requests_per_minute:
                retry_after = max(1, int(self.window_seconds - (now - window[0])))
                return False, retry_after

            window.append(now)

            # Opportunistic cleanup to avoid unbounded growth.
            if len(self._requests) > 10_000:
                expired_keys = [
                    key for key, values in self._requests.items()
                    if not values or values[-1] <= cutoff
                ]
                for key in expired_keys:
                    self._requests.pop(key, None)

            return True, 0

    async def _check_redis_limit(self, client_key: str, now: float) -> tuple[bool, int]:
        assert self._redis is not None

        key = f"rate-limit:{client_key}"
        cutoff = now - self.window_seconds

        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.zremrangebyscore(key, 0, cutoff)
            pipe.zcard(key)
            pipe.zadd(key, {f"{now}:{time.monotonic_ns()}": now})
            pipe.expire(key, self.window_seconds + 5)
            _, count, _, _ = await pipe.execute()

        if count >= self.requests_per_minute:
            oldest = await self._redis.zrange(key, 0, 0, withscores=True)
            retry_after = 1
            if oldest:
                retry_after = max(1, int(self.window_seconds - (now - oldest[0][1])))
            await self._redis.zremrangebyrank(key, self.requests_per_minute, -1)
            return False, retry_after

        return True, 0

    def _get_client_key(self, request: Request) -> str:
        if settings.TRUST_FORWARDED_IP:
            forwarded_for = request.headers.get("x-forwarded-for", "")
            if forwarded_for:
                first = forwarded_for.split(",")[0].strip()
                if first:
                    return first
        if request.client and request.client.host:
            return request.client.host
        return "unknown"


rate_limiter = RateLimiter(requests_per_minute=settings.RATE_LIMIT_PER_MINUTE)
