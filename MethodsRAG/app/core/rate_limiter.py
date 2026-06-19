"""Rate limiting utilities."""

from collections import defaultdict
from threading import Lock
from typing import Optional
import time

from fastapi import Request

from app.core.config import get_settings
from app.core.errors import rate_limit_error
from app.core.logging import logger

settings = get_settings()


class InMemoryRateLimiter:
    """In-memory rate limiter for single-instance deployments."""

    def __init__(self, requests_per_minute: int = 60):
        self.requests_per_minute = requests_per_minute
        self.requests = defaultdict(list)
        self.cleanup_interval = 60
        self.last_cleanup = time.time()
        self._lock = Lock()

    def _cleanup(self, now: float) -> None:
        if now - self.last_cleanup < self.cleanup_interval:
            return

        cutoff_time = now - 60
        for identifier in list(self.requests.keys()):
            self.requests[identifier] = [
                ts for ts in self.requests[identifier] if ts > cutoff_time
            ]
            if not self.requests[identifier]:
                del self.requests[identifier]

        self.last_cleanup = now

    def check(self, identifier: str) -> tuple[bool, Optional[int], int]:
        with self._lock:
            now = time.time()
            self._cleanup(now)
            cutoff_time = now - 60
            self.requests[identifier] = [
                ts for ts in self.requests[identifier] if ts > cutoff_time
            ]

            used = len(self.requests[identifier])
            if used >= self.requests_per_minute:
                oldest_request = min(self.requests[identifier])
                retry_after = max(1, int(60 - (now - oldest_request)) + 1)
                return False, retry_after, 0

            self.requests[identifier].append(now)
            remaining = max(self.requests_per_minute - len(self.requests[identifier]), 0)
            return True, None, remaining

    def get_remaining(self, identifier: str) -> int:
        with self._lock:
            now = time.time()
            self._cleanup(now)
            cutoff_time = now - 60
            self.requests[identifier] = [
                ts for ts in self.requests[identifier] if ts > cutoff_time
            ]
            remaining = self.requests_per_minute - len(self.requests[identifier])
            return max(remaining, 0)


_limiter = InMemoryRateLimiter(requests_per_minute=settings.RATE_LIMIT_PER_MINUTE)


def get_limiter() -> InMemoryRateLimiter:
    return _limiter


def get_client_identifier(request: Request) -> str:
    settings = get_settings()
    if settings.TRUST_FORWARDED_IP:
        x_forwarded_for = request.headers.get("X-Forwarded-For")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()

    return request.client.host if request.client else "unknown"


async def rate_limit_dependency(request: Request) -> str:
    identifier = get_client_identifier(request)
    allowed, retry_after, _remaining = _limiter.check(identifier)

    if not allowed:
        logger.warning(
            f"Rate limit exceeded for client: {identifier}",
            extra={"client_id": identifier, "retry_after": retry_after},
        )
        raise rate_limit_error(retry_after=retry_after or 60)

    return identifier
