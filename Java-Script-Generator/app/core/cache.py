# app/core/cache.py
"""
Caching Layer

Provides caching for LLM responses to reduce costs and latency.
Supports both in-memory and Redis backends.
"""

import asyncio
import hashlib
import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Optional, Any, Dict
from collections import OrderedDict
from dataclasses import dataclass

from app.core.config import get_settings

logger = logging.getLogger("cache")


@dataclass
class CacheEntry:
    """Cached value with metadata."""
    value: Any
    created_at: float
    ttl: int
    hits: int = 0


class BaseCacheBackend(ABC):
    """Abstract cache backend interface."""
    
    @abstractmethod
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        pass
    
    @abstractmethod
    async def set(self, key: str, value: Any, ttl: int) -> bool:
        """Set value in cache."""
        pass
    
    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Delete value from cache."""
        pass
    
    @abstractmethod
    async def clear(self) -> bool:
        """Clear all cached values."""
        pass
    
    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        pass


class InMemoryCache(BaseCacheBackend):
    """
    Simple in-memory cache implementation.
    
    Suitable for single-instance deployments.
    """
    
    def __init__(self, max_size: int = 1000):
        self._cache = OrderedDict()
        self._max_size = max_size
        self._hits = 0
        self._misses = 0
        self._lock = asyncio.Lock()  # Guards all mutations to _cache
    
    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            entry = self._cache.get(key)

            if entry is None:
                self._misses += 1
                return None

            # Check TTL
            if time.time() - entry.created_at > entry.ttl:
                del self._cache[key]
                self._misses += 1
                return None

            # Move to end to track LRU order
            self._cache.move_to_end(key)
            entry.hits += 1
            self._hits += 1
            return entry.value
    
    async def set(self, key: str, value: Any, ttl: int) -> bool:
        async with self._lock:
            # Update existing entry in-place
            if key in self._cache:
                self._cache[key] = CacheEntry(
                    value=value,
                    created_at=time.time(),
                    ttl=ttl,
                )
                self._cache.move_to_end(key)
                return True

            # Evict oldest entries if at capacity
            if len(self._cache) >= self._max_size:
                self._cache.popitem(last=False)

            self._cache[key] = CacheEntry(
                value=value,
                created_at=time.time(),
                ttl=ttl,
            )
            return True
    
    async def delete(self, key: str) -> bool:
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    async def clear(self) -> bool:
        async with self._lock:
            self._cache.clear()
            return True
    
    def get_stats(self) -> Dict[str, Any]:
        total_requests = self._hits + self._misses
        hit_rate = self._hits / total_requests if total_requests > 0 else 0.0
        
        return {
            "backend": "in_memory",
            "size": len(self._cache),
            "max_size": self._max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(hit_rate, 4),
        }


class RedisCache(BaseCacheBackend):
    """
    Redis-based cache implementation.
    
    Suitable for distributed deployments.
    Requires 'redis' package.
    """
    
    def __init__(self, redis_url: str):
        self._redis_url = redis_url
        self._client = None
        self._hits = 0
        self._misses = 0
        
        try:
            import redis.asyncio as redis
            self._client = redis.from_url(redis_url, decode_responses=True)
            logger.info("Redis cache initialized")
        except ImportError:
            logger.warning("Redis package not installed, cache disabled")
        except Exception as e:
            logger.error("Failed to connect to Redis: %s", e)
    
    @property
    def is_available(self) -> bool:
        return self._client is not None
    
    async def get(self, key: str) -> Optional[Any]:
        if not self.is_available:
            return None
        
        try:
            value = await self._client.get(f"llm_cache:{key}")
            if value is None:
                self._misses += 1
                return None
            
            self._hits += 1
            return json.loads(value)
        except Exception as e:
            logger.error("Redis get error: %s", e)
            self._misses += 1
            return None
    
    async def set(self, key: str, value: Any, ttl: int) -> bool:
        if not self.is_available:
            return False
        
        try:
            await self._client.setex(
                f"llm_cache:{key}",
                ttl,
                json.dumps(value),
            )
            return True
        except Exception as e:
            logger.error("Redis set error: %s", e)
            return False
    
    async def delete(self, key: str) -> bool:
        if not self.is_available:
            return False
        
        try:
            await self._client.delete(f"llm_cache:{key}")
            return True
        except Exception as e:
            logger.error("Redis delete error: %s", e)
            return False
    
    async def clear(self) -> bool:
        if not self.is_available:
            return False
        try:
            cursor = 0
            while True:
                cursor, keys = await self._client.scan(cursor, match="llm_cache:*", count=100)
                if keys:
                    await self._client.delete(*keys)
                if cursor == 0:
                    break
            return True
        except Exception as e:
            logger.error("Redis clear error: %s", e)
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        total_requests = self._hits + self._misses
        hit_rate = self._hits / total_requests if total_requests > 0 else 0.0
        
        return {
            "backend": "redis",
            "available": self.is_available,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(hit_rate, 4),
        }


class LLMCache:
    """
    High-level cache interface for LLM responses.
    
    Features:
    - Automatic cache key generation from prompts
    - Configurable TTL
    - Backend abstraction (memory/Redis)
    """
    
    def __init__(self):
        settings = get_settings()
        
        self._enabled = settings.CACHE_ENABLED
        self._ttl = settings.CACHE_TTL_SECONDS
        
        # Initialize backend
        if settings.REDIS_URL:
            self._backend = RedisCache(settings.REDIS_URL)
            if not self._backend.is_available:
                logger.warning("Redis unavailable, falling back to in-memory cache")
                self._backend = InMemoryCache()
        else:
            self._backend = InMemoryCache()
        
        logger.info(
            "LLMCache initialized | enabled=%s | backend=%s | ttl=%ds",
            self._enabled,
            type(self._backend).__name__,
            self._ttl,
        )
    
    @staticmethod
    def _normalize_prompt(prompt: str) -> str:
        """Normalize prompt to improve cache hit rate.

        Collapses whitespace and strips so that minor formatting differences
        in otherwise identical prompts still hit the cache.
        """
        import re as _re
        return _re.sub(r"\s+", " ", prompt.strip().lower())

    @staticmethod
    def _generate_key(prompt: str, purpose: str) -> str:
        """Generate a cache key from prompt content."""
        normalized = LLMCache._normalize_prompt(prompt)
        content = f"{purpose}:{normalized}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]
    
    async def get(self, prompt: str, purpose: str) -> Optional[str]:
        """
        Get cached LLM response.
        
        Args:
            prompt: The LLM prompt
            purpose: Purpose identifier
            
        Returns:
            Cached response text or None
        """
        if not self._enabled:
            return None
        
        key = self._generate_key(prompt, purpose)
        result = await self._backend.get(key)
        
        if result is not None:
            logger.debug("Cache HIT | purpose=%s | key=%s", purpose, key[:8])
        
        return result
    
    async def set(self, prompt: str, purpose: str, response: str) -> bool:
        """
        Cache an LLM response.
        
        Args:
            prompt: The LLM prompt
            purpose: Purpose identifier
            response: The response to cache
            
        Returns:
            True if cached successfully
        """
        if not self._enabled:
            return False
        
        key = self._generate_key(prompt, purpose)
        success = await self._backend.set(key, response, self._ttl)
        
        if success:
            logger.debug("Cache SET | purpose=%s | key=%s", purpose, key[:8])
        
        return success
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            "enabled": self._enabled,
            "ttl_seconds": self._ttl,
            **self._backend.get_stats(),
        }


# Global cache instance
_llm_cache: Optional[LLMCache] = None


def get_llm_cache() -> LLMCache:
    """Get or create the LLM cache instance."""
    global _llm_cache
    
    if _llm_cache is None:
        _llm_cache = LLMCache()
    
    return _llm_cache

