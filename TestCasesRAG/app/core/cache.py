import hashlib
from typing import Any, Optional

from app.core.cache_layer import cache_manager
from app.core.config import get_settings
from app.core.logging import logger
from app.core.metrics import Metrics

settings = get_settings()
SEARCH_CACHE_NAMESPACE = "search"
_NAMESPACE_TTL_SECONDS = 60 * 60 * 24 * 30


def _hashed_key(key: str) -> str:
    return hashlib.sha256(str(key or "").encode("utf-8")).hexdigest()


async def _get_namespace_version(namespace: str) -> int:
    version_key = f"namespace:{namespace}:version"
    value = await cache_manager.get(version_key)

    try:
        parsed = int(value)
        if parsed > 0:
            return parsed
    except Exception:
        pass

    await cache_manager.set(version_key, 1, ttl_seconds=_NAMESPACE_TTL_SECONDS)
    return 1


async def _set_namespace_version(namespace: str, version: int) -> None:
    version_key = f"namespace:{namespace}:version"
    await cache_manager.set(version_key, int(version), ttl_seconds=_NAMESPACE_TTL_SECONDS)


async def _build_namespaced_key(namespace: str, key: str) -> str:
    version = await _get_namespace_version(namespace)
    return f"{namespace}:v{version}:{_hashed_key(key)}"


async def get_search_cache(key: str) -> Optional[Any]:
    if not settings.CACHE_ENABLED:
        return None

    try:
        cache_key = await _build_namespaced_key(SEARCH_CACHE_NAMESPACE, key)
        value = await cache_manager.get(cache_key)
        if value is None:
            Metrics.record_cache_miss()
            return None

        Metrics.record_cache_hit()
        return value
    except Exception as err:
        logger.warning("search_cache_get_failed", extra={"error": str(err)})
        Metrics.record_cache_miss()
        return None


async def cache_get(key: str) -> Optional[Any]:
    """Backward-compatible alias for older tests and callers."""
    return await get_search_cache(key)


async def set_search_cache(key: str, value: Any) -> None:
    if not settings.CACHE_ENABLED:
        return

    try:
        cache_key = await _build_namespaced_key(SEARCH_CACHE_NAMESPACE, key)
        await cache_manager.set(cache_key, value, ttl_seconds=settings.CACHE_TTL_SECONDS)
    except Exception as err:
        logger.warning("search_cache_set_failed", extra={"error": str(err)})


async def cache_set(key: str, value: Any) -> None:
    """Backward-compatible alias for older tests and callers."""
    await set_search_cache(key, value)


async def invalidate_search_cache(reason: str = "mutation") -> int:
    current_version = await _get_namespace_version(SEARCH_CACHE_NAMESPACE)
    next_version = current_version + 1
    await _set_namespace_version(SEARCH_CACHE_NAMESPACE, next_version)

    logger.info(
        "search_cache_invalidated",
        extra={"reason": reason, "namespace_version": next_version},
    )
    return next_version


async def get_cache_health() -> dict:
    return await cache_manager.get_stats()
