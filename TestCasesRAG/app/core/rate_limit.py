from datetime import datetime, timedelta, timezone
from typing import Dict, List
from threading import RLock

from app.core.config import get_settings
from app.core.logging import logger

settings = get_settings()


class RateLimiter:
    def __init__(self, requests_per_minute: int = 60):
        self.requests_per_minute = requests_per_minute
        self.window_seconds = 60
        self.request_times: Dict[str, List[datetime]] = {}
        self._lock = RLock()

    def is_allowed(self, client_id: str) -> bool:
        """Check if client is within rate limit"""
        try:
            with self._lock:
                now = datetime.now(timezone.utc)
                cutoff = now - timedelta(seconds=self.window_seconds)

                # Initialize if not exists
                if client_id not in self.request_times:
                    self.request_times[client_id] = []

                client_requests = self.request_times[client_id]

                # Remove old requests outside window
                client_requests[:] = [
                    req_time for req_time in client_requests
                    if req_time > cutoff
                ]

                # Check limit
                if len(client_requests) >= self.requests_per_minute:
                    return False

                # Record this request
                client_requests.append(now)
                return True

        except Exception as e:
            logger.warning(
                "rate_limiter_error",
                extra={"error": str(e), "client_id": client_id},
            )
            # On error, allow request to proceed
            return True

    def get_remaining(self, client_id: str) -> int:
        """Get remaining requests for client"""
        try:
            with self._lock:
                if client_id not in self.request_times:
                    return self.requests_per_minute

                now = datetime.now(timezone.utc)
                cutoff = now - timedelta(seconds=self.window_seconds)

                client_requests = self.request_times.get(client_id, [])

                recent = [
                    t for t in client_requests
                    if t > cutoff
                ]

                return max(0, self.requests_per_minute - len(recent))

        except Exception:
            return self.requests_per_minute


# Global rate limiter instance
_limiter = RateLimiter(requests_per_minute=settings.RATE_LIMIT_REQUESTS_PER_MINUTE)


def get_limiter() -> RateLimiter:
    return _limiter