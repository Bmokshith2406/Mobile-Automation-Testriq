"""
Unified cache layer with optional Redis support and safe memory fallback.
"""

from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any, Dict, Optional
import json

from app.core.config import get_settings
from app.core.logging import logger

settings = get_settings()


class MemoryCache:
    """Thread-safe in-memory cache with TTL and LRU eviction."""

    def __init__(self, max_size: int = settings.CACHE_MAX_SIZE):
        self.max_size = max_size
        self.cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self.lock = RLock()

    def set(self, key: str, value: Any, ttl_seconds: int = settings.CACHE_TTL_SECONDS) -> None:
        with self.lock:
            self._evict_expired()

            if key in self.cache:
                del self.cache[key]

            self.cache[key] = {
                "value": value,
                "expires_at": datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
            }

            if len(self.cache) > self.max_size:
                oldest_key = next(iter(self.cache))
                del self.cache[oldest_key]
                logger.debug("cache_lru_eviction", extra={"key": oldest_key})

    def get(self, key: str) -> Optional[Any]:
        with self.lock:
            entry = self.cache.get(key)
            if entry is None:
                return None

            if datetime.now(timezone.utc) > entry["expires_at"]:
                del self.cache[key]
                return None

            self.cache.move_to_end(key)
            return entry["value"]

    def delete(self, key: str) -> None:
        with self.lock:
            self.cache.pop(key, None)

    def clear(self) -> None:
        with self.lock:
            self.cache.clear()

    def _evict_expired(self) -> None:
        now = datetime.now(timezone.utc)
        expired = [
            key
            for key, value in self.cache.items()
            if now > value["expires_at"]
        ]
        for key in expired:
            del self.cache[key]

    def get_stats(self) -> Dict[str, Any]:
        with self.lock:
            self._evict_expired()
            size = len(self.cache)
            return {
                "size": size,
                "max_size": self.max_size,
                "usage_percent": (size / self.max_size * 100) if self.max_size else 0,
            }


class CacheManager:
    """Cache manager with Redis-first optional backend and memory fallback."""

    def __init__(self):
        self.memory_cache = MemoryCache()
        self.redis_client = None
        self.use_redis = False
        self.backend_name = "disabled"
        self.initialized = False
        self._prefix = f"{settings.CACHE_KEY_PREFIX}:"

    def _full_key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    async def init(self) -> None:
        self.initialized = True

        if not settings.CACHE_ENABLED:
            self.backend_name = "disabled"
            logger.info("cache_disabled")
            return

        backend = settings.CACHE_BACKEND
        if backend not in {"auto", "memory", "redis"}:
            logger.warning("invalid_cache_backend_falling_back_to_memory", extra={"backend": backend})
            backend = "memory"

        if backend == "memory":
            self.backend_name = "memory"
            logger.info("memory_cache_initialized")
            return

        redis_url = (settings.REDIS_URL or "").strip()
        if not redis_url:
            if backend == "redis":
                raise RuntimeError("REDIS_URL must be configured when CACHE_BACKEND=redis.")

            self.backend_name = "memory"
            logger.info("redis_url_not_configured_using_memory_cache")
            return

        try:
            try:
                from redis import asyncio as redis_async

                self.redis_client = redis_async.from_url(
                    redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                )
            except Exception:
                import aioredis

                self.redis_client = await aioredis.from_url(
                    redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                )

            await self.redis_client.ping()
            self.use_redis = True
            self.backend_name = "redis"
            logger.info("redis_cache_initialized")
        except Exception as err:
            self.redis_client = None
            self.use_redis = False

            if backend == "redis":
                raise RuntimeError(f"Redis cache initialization failed: {err}") from err

            self.backend_name = "memory"
            logger.warning(
                "redis_initialization_failed_falling_back_to_memory",
                extra={"error": str(err)},
            )

    async def set(self, key: str, value: Any, ttl_seconds: int = settings.CACHE_TTL_SECONDS) -> None:
        if not settings.CACHE_ENABLED:
            return

        full_key = self._full_key(key)

        try:
            if self.use_redis and self.redis_client:
                try:
                    serialized = json.dumps(value, default=str)
                except Exception:
                    serialized = json.dumps(str(value))
                await self.redis_client.setex(full_key, int(ttl_seconds), serialized)
            else:
                self.memory_cache.set(full_key, value, ttl_seconds)
        except Exception as err:
            logger.warning("cache_set_failed", extra={"error": str(err), "key": key})

    async def get(self, key: str) -> Optional[Any]:
        if not settings.CACHE_ENABLED:
            return None

        full_key = self._full_key(key)

        try:
            if self.use_redis and self.redis_client:
                value = await self.redis_client.get(full_key)
                if value is None:
                    return None
                try:
                    return json.loads(value)
                except Exception:
                    return value

            return self.memory_cache.get(full_key)
        except Exception as err:
            logger.warning("cache_get_failed", extra={"error": str(err), "key": key})
            return None

    async def delete(self, key: str) -> None:
        full_key = self._full_key(key)

        try:
            if self.use_redis and self.redis_client:
                await self.redis_client.delete(full_key)
            else:
                self.memory_cache.delete(full_key)
        except Exception as err:
            logger.warning("cache_delete_failed", extra={"error": str(err), "key": key})

    async def clear(self) -> None:
        try:
            if self.use_redis and self.redis_client:
                pattern = self._full_key("*")
                try:
                    keys = []
                    async for key in self.redis_client.scan_iter(match=pattern):
                        keys.append(key)
                    if keys:
                        await self.redis_client.delete(*keys)
                except TypeError:
                    keys = await self.redis_client.keys(pattern)
                    if keys:
                        await self.redis_client.delete(*keys)
            else:
                self.memory_cache.clear()
        except Exception as err:
            logger.warning("cache_clear_failed", extra={"error": str(err)})

    async def get_stats(self) -> Dict[str, Any]:
        stats = {
            "enabled": settings.CACHE_ENABLED,
            "backend": self.backend_name,
        }

        if not settings.CACHE_ENABLED:
            stats["status"] = "disabled"
            return stats

        if self.use_redis and self.redis_client:
            try:
                dbsize = await self.redis_client.dbsize()
                stats.update({
                    "status": "healthy",
                    "redis_dbsize": dbsize,
                })
                return stats
            except Exception as err:
                stats.update({
                    "status": "degraded",
                    "error": str(err),
                })
                return stats

        stats.update({
            "status": "healthy",
            "memory": self.memory_cache.get_stats(),
        })
        return stats

    async def close(self) -> None:
        if self.redis_client is None:
            return

        try:
            close_fn = getattr(self.redis_client, "aclose", None) or getattr(self.redis_client, "close", None)
            if close_fn is not None:
                result = close_fn()
                if hasattr(result, "__await__"):
                    await result
        except Exception as err:
            logger.warning("redis_close_failed", extra={"error": str(err)})
        finally:
            self.redis_client = None
            self.use_redis = False


cache_manager = CacheManager()
