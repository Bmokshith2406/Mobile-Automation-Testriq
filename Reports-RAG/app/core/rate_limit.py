from collections import defaultdict, deque
from dataclasses import dataclass, field
from threading import Lock
import time

from app.core.config import settings


@dataclass
class InMemoryRateLimiter:
    enabled: bool
    max_requests: int
    window_seconds: int
    _events: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(deque))
    _lock: Lock = field(default_factory=Lock)

    def _prune(self, client_id: str, now: float) -> deque[float]:
        window = self._events[client_id]
        cutoff = now - self.window_seconds
        while window and window[0] <= cutoff:
            window.popleft()
        return window

    def is_allowed(self, client_id: str) -> bool:
        if not self.enabled:
            return True

        now = time.monotonic()
        with self._lock:
            window = self._prune(client_id, now)
            if len(window) >= self.max_requests:
                return False
            window.append(now)
            return True

    def get_remaining(self, client_id: str) -> int | None:
        if not self.enabled:
            return None

        now = time.monotonic()
        with self._lock:
            window = self._prune(client_id, now)
            return max(self.max_requests - len(window), 0)


_limiter = InMemoryRateLimiter(
    enabled=settings.ENABLE_RATE_LIMITING,
    max_requests=settings.RATE_LIMIT_REQUESTS,
    window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
)


def get_limiter() -> InMemoryRateLimiter:
    return _limiter
