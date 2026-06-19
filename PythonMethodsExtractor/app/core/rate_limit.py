from collections import defaultdict, deque
from threading import Lock

from app.core.config import get_settings


class SlidingWindowRateLimiter:
    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._lock = Lock()
        self._buckets: dict[str, deque[float]] = defaultdict(deque)

    @property
    def enabled(self) -> bool:
        return self.max_requests > 0 and self.window_seconds > 0

    def _prune(self, key: str, now: float) -> deque[float]:
        bucket = self._buckets[key]
        cutoff = now - self.window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        return bucket

    def is_allowed(self, key: str, now: float | None = None) -> bool:
        if not self.enabled:
            return True

        current = now if now is not None else __import__("time").time()
        with self._lock:
            bucket = self._prune(key, current)
            if len(bucket) >= self.max_requests:
                return False
            bucket.append(current)
            return True

    def get_remaining(self, key: str, now: float | None = None) -> int | None:
        if not self.enabled:
            return None

        current = now if now is not None else __import__("time").time()
        with self._lock:
            bucket = self._prune(key, current)
            return max(self.max_requests - len(bucket), 0)


_limiter: SlidingWindowRateLimiter | None = None


def get_limiter() -> SlidingWindowRateLimiter:
    global _limiter
    if _limiter is None:
        settings = get_settings()
        _limiter = SlidingWindowRateLimiter(
            max_requests=settings.RATE_LIMIT_REQUESTS,
            window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
        )
    return _limiter
