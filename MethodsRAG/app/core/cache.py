import time
from threading import RLock
from typing import Any, Dict, Tuple

from app.core.config import get_settings
from app.core.metrics import Metrics

settings = get_settings()

# Simple in-memory cache; can later swap with Redis
SEARCH_CACHE: Dict[str, Tuple[float, Any]] = {}
_cache_lock = RLock()


def cache_get(key: str):
    try:
        with _cache_lock:
            entry = SEARCH_CACHE.get(key)
    except Exception:
        return None

    if not entry:
        Metrics.record_cache_miss()
        return None

    try:
        ts, value = entry
    except Exception:
        # Corrupt entry — remove safely
        try:
            with _cache_lock:
                del SEARCH_CACHE[key]
        except Exception:
            pass
        return None

    try:
        if time.time() - ts > settings.CACHE_TTL_SECONDS:
            try:
                with _cache_lock:
                    del SEARCH_CACHE[key]
            except Exception:
                pass
            return None
    except Exception:
        # If time or TTL computation fails, treat as expired
        try:
            with _cache_lock:
                del SEARCH_CACHE[key]
        except Exception:
            pass
        return None

    Metrics.record_cache_hit()
    return value


def cache_set(key: str, value: Any):
    try:
        with _cache_lock:
            SEARCH_CACHE[key] = (time.time(), value)
    except Exception:
        # Never allow cache write failure to break app flow
        pass


def cache_clear() -> None:
    try:
        with _cache_lock:
            SEARCH_CACHE.clear()
    except Exception:
        pass


def cache_size() -> int:
    try:
        with _cache_lock:
            return len(SEARCH_CACHE)
    except Exception:
        return 0
