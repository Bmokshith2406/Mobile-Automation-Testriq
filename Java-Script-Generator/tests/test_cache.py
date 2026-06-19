# tests/test_cache.py
"""
Tests for InMemoryCache (app/core/cache.py)

Covers:
- Basic get/set/delete
- TTL expiry
- LRU eviction when at max_size
- Concurrent access safety (asyncio lock)
- Stats accuracy (hits, misses, hit_rate)
- clear() resets state
"""

import asyncio
import time
import pytest
from app.core.cache import InMemoryCache, CacheEntry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cache():
    return InMemoryCache(max_size=5)


# ---------------------------------------------------------------------------
# Basic CRUD
# ---------------------------------------------------------------------------

class TestBasicOperations:

    @pytest.mark.asyncio
    async def test_set_and_get(self, cache):
        await cache.set("k1", "hello", ttl=60)
        result = await cache.get("k1")
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self, cache):
        result = await cache.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_existing_key(self, cache):
        await cache.set("k2", "world", ttl=60)
        deleted = await cache.delete("k2")
        assert deleted is True
        assert await cache.get("k2") is None

    @pytest.mark.asyncio
    async def test_delete_missing_key_returns_false(self, cache):
        assert await cache.delete("ghost") is False

    @pytest.mark.asyncio
    async def test_clear_removes_all_entries(self, cache):
        await cache.set("a", 1, ttl=60)
        await cache.set("b", 2, ttl=60)
        await cache.clear()
        assert await cache.get("a") is None
        assert await cache.get("b") is None


# ---------------------------------------------------------------------------
# TTL
# ---------------------------------------------------------------------------

class TestTtlExpiry:

    @pytest.mark.asyncio
    async def test_expired_entry_returns_none(self, cache):
        await cache.set("ttl_key", "value", ttl=1)
        # Manually backdate the entry so it appears expired
        cache._cache["ttl_key"].created_at = time.time() - 2
        result = await cache.get("ttl_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_non_expired_entry_returned(self, cache):
        await cache.set("fresh", "data", ttl=3600)
        assert await cache.get("fresh") == "data"


# ---------------------------------------------------------------------------
# LRU eviction
# ---------------------------------------------------------------------------

class TestLruEviction:

    @pytest.mark.asyncio
    async def test_oldest_entry_evicted_when_full(self):
        c = InMemoryCache(max_size=3)
        await c.set("first", 1, ttl=60)
        await c.set("second", 2, ttl=60)
        await c.set("third", 3, ttl=60)
        # Adding fourth should evict "first"
        await c.set("fourth", 4, ttl=60)
        assert await c.get("first") is None
        assert await c.get("fourth") == 4

    @pytest.mark.asyncio
    async def test_accessed_entry_not_evicted(self):
        c = InMemoryCache(max_size=3)
        await c.set("a", 1, ttl=60)
        await c.set("b", 2, ttl=60)
        await c.set("c", 3, ttl=60)
        # Access "a" to move it to the end (most recently used)
        await c.get("a")
        # Now add "d" — "b" should be evicted (now the oldest)
        await c.set("d", 4, ttl=60)
        assert await c.get("a") == 1
        assert await c.get("b") is None


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

class TestStats:

    @pytest.mark.asyncio
    async def test_hit_increments_hits(self, cache):
        await cache.set("s", "v", ttl=60)
        await cache.get("s")
        await cache.get("s")
        stats = cache.get_stats()
        assert stats["hits"] == 2

    @pytest.mark.asyncio
    async def test_miss_increments_misses(self, cache):
        await cache.get("nope")
        stats = cache.get_stats()
        assert stats["misses"] == 1

    @pytest.mark.asyncio
    async def test_hit_rate_calculation(self, cache):
        await cache.set("x", 1, ttl=60)
        await cache.get("x")   # hit
        await cache.get("x")   # hit
        await cache.get("y")   # miss
        stats = cache.get_stats()
        assert stats["hit_rate"] == pytest.approx(2 / 3, abs=0.01)


# ---------------------------------------------------------------------------
# Concurrency safety
# ---------------------------------------------------------------------------

class TestConcurrency:

    @pytest.mark.asyncio
    async def test_concurrent_sets_do_not_corrupt_state(self):
        c = InMemoryCache(max_size=100)
        keys = [f"key_{i}" for i in range(50)]

        async def writer(k):
            await c.set(k, k, ttl=60)

        await asyncio.gather(*[writer(k) for k in keys])
        # All keys should be reachable (no corruption)
        for k in keys:
            assert await c.get(k) == k

    @pytest.mark.asyncio
    async def test_concurrent_reads_do_not_corrupt_state(self):
        c = InMemoryCache(max_size=10)
        await c.set("shared", "value", ttl=60)

        async def reader():
            return await c.get("shared")

        results = await asyncio.gather(*[reader() for _ in range(20)])
        assert all(r == "value" for r in results)
