# app/core/redis_state.py
"""
Redis-backed distributed state management.
Provides shared state across multiple instances for horizontal scaling.
"""

from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import json
import logging
import asyncio

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None

from app.core.config import settings

logger = logging.getLogger(__name__)


# ==============================================================================
# REDIS CONNECTION POOL
# ==============================================================================

class RedisConnectionPool:
    """
    Singleton Redis connection pool manager.
    Handles connection lifecycle and health checking.
    """
    
    _instance: Optional["RedisConnectionPool"] = None
    _lock: asyncio.Lock = asyncio.Lock()
    
    def __init__(self):
        self._pool: Optional[redis.ConnectionPool] = None
        self._client: Optional[redis.Redis] = None
        self._is_connected: bool = False
    
    @classmethod
    async def get_instance(cls) -> "RedisConnectionPool":
        """Get or create the singleton instance."""
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
                    await cls._instance._initialize()
        return cls._instance
    
    async def _initialize(self) -> None:
        """Initialize the Redis connection pool."""
        if not REDIS_AVAILABLE:
            logger.warning("Redis package not installed, state store disabled")
            return
        
        if not settings.redis.enabled:
            logger.info("Redis state store disabled by configuration")
            return
        
        try:
            self._pool = redis.ConnectionPool.from_url(
                settings.redis.url,
                max_connections=settings.redis.max_connections,
                decode_responses=True,
            )
            self._client = redis.Redis(connection_pool=self._pool)
            
            # Test connection
            await self._client.ping()
            self._is_connected = True
            logger.info("Redis connection pool initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Redis connection: {e}")
            self._is_connected = False
    
    @property
    def client(self) -> Optional[redis.Redis]:
        """Get the Redis client."""
        return self._client if self._is_connected else None
    
    @property
    def is_connected(self) -> bool:
        """Check if Redis is connected."""
        return self._is_connected
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform a health check on the Redis connection."""
        if not self._is_connected:
            return {
                "status": "unavailable",
                "message": "Redis not connected",
            }
        
        try:
            start = datetime.utcnow()
            await self._client.ping()
            latency = (datetime.utcnow() - start).total_seconds() * 1000
            
            info = await self._client.info("server")
            
            return {
                "status": "healthy",
                "latency_ms": round(latency, 2),
                "redis_version": info.get("redis_version"),
                "connected_clients": info.get("connected_clients"),
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "message": str(e),
            }
    
    async def close(self) -> None:
        """Close the Redis connection pool."""
        if self._client:
            await self._client.close()
        if self._pool:
            await self._pool.disconnect()
        self._is_connected = False
        logger.info("Redis connection pool closed")


# ==============================================================================
# DISTRIBUTED EXECUTION CONTEXT
# ==============================================================================

class DistributedExecutionContext:
    """
    Redis-backed execution context for distributed state management.
    Enables horizontal scaling by sharing state across instances.
    """
    
    KEY_PREFIX = "repair_engine:execution"
    DEFAULT_TTL = 3600  # 1 hour
    
    def __init__(
        self,
        execution_id: str,
        redis_client: Optional[redis.Redis] = None,
    ):
        self.execution_id = execution_id
        self._redis = redis_client
        self._key = f"{self.KEY_PREFIX}:{execution_id}"
    
    @classmethod
    async def create(
        cls,
        execution_id: str,
        ttl: int = DEFAULT_TTL,
    ) -> "DistributedExecutionContext":
        """Create a new distributed execution context."""
        pool = await RedisConnectionPool.get_instance()
        instance = cls(execution_id, pool.client)
        
        if instance._redis:
            # Initialize context with metadata
            await instance._redis.hset(
                instance._key,
                mapping={
                    "execution_id": execution_id,
                    "created_at": datetime.utcnow().isoformat(),
                    "status": "initialized",
                }
            )
            await instance._redis.expire(instance._key, ttl)
        
        return instance
    
    @classmethod
    async def get(
        cls,
        execution_id: str,
    ) -> Optional["DistributedExecutionContext"]:
        """Get an existing execution context."""
        pool = await RedisConnectionPool.get_instance()
        
        if not pool.client:
            return None
        
        key = f"{cls.KEY_PREFIX}:{execution_id}"
        exists = await pool.client.exists(key)
        
        if not exists:
            return None
        
        return cls(execution_id, pool.client)
    
    async def get_attempt_count(self, step_id: str) -> int:
        """Get the current attempt count for a step."""
        if not self._redis:
            return 0
        
        count = await self._redis.hget(self._key, f"attempts:{step_id}")
        return int(count) if count else 0
    
    async def increment_attempt(self, step_id: str) -> int:
        """Increment and return the attempt count for a step."""
        if not self._redis:
            return 1
        
        return await self._redis.hincrby(self._key, f"attempts:{step_id}", 1)
    
    async def set_step_status(
        self,
        step_id: str,
        status: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Set the status for a step."""
        if not self._redis:
            return
        
        data = {
            f"status:{step_id}": status,
            f"status_updated:{step_id}": datetime.utcnow().isoformat(),
        }
        
        if metadata:
            data[f"metadata:{step_id}"] = json.dumps(metadata)
        
        await self._redis.hset(self._key, mapping=data)
    
    async def get_step_status(self, step_id: str) -> Optional[str]:
        """Get the status for a step."""
        if not self._redis:
            return None
        
        return await self._redis.hget(self._key, f"status:{step_id}")
    
    async def record_failure(
        self,
        step_id: str,
        error_type: str,
        error_message: str,
    ) -> None:
        """Record a failure for a step."""
        if not self._redis:
            return
        
        failure_key = f"{self._key}:failures:{step_id}"
        failure_data = {
            "error_type": error_type,
            "error_message": error_message,
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        await self._redis.rpush(failure_key, json.dumps(failure_data))
        await self._redis.expire(failure_key, self.DEFAULT_TTL)
    
    async def get_failures(self, step_id: str) -> List[Dict[str, Any]]:
        """Get all failures for a step."""
        if not self._redis:
            return []
        
        failure_key = f"{self._key}:failures:{step_id}"
        failures = await self._redis.lrange(failure_key, 0, -1)
        
        return [json.loads(f) for f in failures]
    
    async def set_context_data(
        self,
        key: str,
        value: Any,
    ) -> None:
        """Set arbitrary context data."""
        if not self._redis:
            return
        
        if isinstance(value, (dict, list)):
            value = json.dumps(value)
        
        await self._redis.hset(self._key, key, str(value))
    
    async def get_context_data(self, key: str) -> Optional[str]:
        """Get arbitrary context data."""
        if not self._redis:
            return None
        
        return await self._redis.hget(self._key, key)
    
    async def get_all_data(self) -> Dict[str, Any]:
        """Get all context data."""
        if not self._redis:
            return {}
        
        return await self._redis.hgetall(self._key)
    
    async def extend_ttl(self, ttl: int = DEFAULT_TTL) -> None:
        """Extend the TTL of the context."""
        if not self._redis:
            return
        
        await self._redis.expire(self._key, ttl)
    
    async def delete(self) -> None:
        """Delete the execution context."""
        if not self._redis:
            return
        
        # Delete main key and all related keys
        keys = [key async for key in self._redis.scan_iter(match=f"{self._key}*")]
        if keys:
            await self._redis.delete(*keys)


# ==============================================================================
# DISTRIBUTED CIRCUIT BREAKER
# ==============================================================================

class DistributedCircuitBreaker:
    """
    Redis-backed circuit breaker for distributed systems.
    Shares circuit state across all instances.
    """
    
    KEY_PREFIX = "repair_engine:circuit_breaker"
    
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        redis_client: Optional[redis.Redis] = None,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._redis = redis_client
        self._key = f"{self.KEY_PREFIX}:{name}"
    
    @classmethod
    async def create(
        cls,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
    ) -> "DistributedCircuitBreaker":
        """Create a distributed circuit breaker."""
        pool = await RedisConnectionPool.get_instance()
        return cls(name, failure_threshold, recovery_timeout, pool.client)
    
    async def is_open(self) -> bool:
        """Check if the circuit is open (blocking requests)."""
        if not self._redis:
            return False
        
        state = await self._redis.hget(self._key, "state")
        
        if state == "open":
            # Check if recovery timeout has passed
            opened_at = await self._redis.hget(self._key, "opened_at")
            if opened_at:
                opened_time = datetime.fromisoformat(opened_at)
                if datetime.utcnow() - opened_time > timedelta(seconds=self.recovery_timeout):
                    # Transition to half-open
                    await self._redis.hset(self._key, "state", "half-open")
                    return False
            return True
        
        return False
    
    async def record_success(self) -> None:
        """Record a successful operation."""
        if not self._redis:
            return
        
        await self._redis.hset(
            self._key,
            mapping={
                "state": "closed",
                "failure_count": "0",
                "last_success": datetime.utcnow().isoformat(),
            }
        )
    
    async def record_failure(self) -> bool:
        """
        Record a failed operation.
        Returns True if the circuit has opened.
        """
        if not self._redis:
            return False
        
        failure_count = await self._redis.hincrby(self._key, "failure_count", 1)
        await self._redis.hset(
            self._key,
            "last_failure",
            datetime.utcnow().isoformat()
        )
        
        if failure_count >= self.failure_threshold:
            await self._redis.hset(
                self._key,
                mapping={
                    "state": "open",
                    "opened_at": datetime.utcnow().isoformat(),
                }
            )
            logger.warning(f"Circuit breaker '{self.name}' opened after {failure_count} failures")
            return True
        
        return False
    
    async def get_state(self) -> Dict[str, Any]:
        """Get the current circuit breaker state."""
        if not self._redis:
            return {"state": "unknown", "redis_unavailable": True}
        
        data = await self._redis.hgetall(self._key)
        return {
            "name": self.name,
            "state": data.get("state", "closed"),
            "failure_count": int(data.get("failure_count", 0)),
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
            "last_failure": data.get("last_failure"),
            "last_success": data.get("last_success"),
            "opened_at": data.get("opened_at"),
        }
    
    async def reset(self) -> None:
        """Reset the circuit breaker to closed state."""
        if not self._redis:
            return
        
        await self._redis.delete(self._key)
        logger.info(f"Circuit breaker '{self.name}' reset")


# ==============================================================================
# DISTRIBUTED RATE LIMITER
# ==============================================================================

class DistributedRateLimiter:
    """
    Redis-backed sliding window rate limiter.
    Enforces rate limits across all instances.
    """
    
    KEY_PREFIX = "repair_engine:rate_limit"
    
    def __init__(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
        redis_client: Optional[redis.Redis] = None,
    ):
        self.key = key
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._redis = redis_client
        self._redis_key = f"{self.KEY_PREFIX}:{key}"
    
    @classmethod
    async def create(
        cls,
        key: str,
        max_requests: int = 100,
        window_seconds: int = 60,
    ) -> "DistributedRateLimiter":
        """Create a distributed rate limiter."""
        pool = await RedisConnectionPool.get_instance()
        return cls(key, max_requests, window_seconds, pool.client)
    
    async def is_allowed(self) -> bool:
        """
        Check if a request is allowed under the rate limit.
        Uses sliding window algorithm.
        """
        if not self._redis:
            return True  # Allow if Redis unavailable
        
        now = datetime.utcnow().timestamp()
        window_start = now - self.window_seconds
        
        # Remove old entries
        await self._redis.zremrangebyscore(self._redis_key, "-inf", window_start)
        
        # Count current requests
        current_count = await self._redis.zcard(self._redis_key)
        
        if current_count >= self.max_requests:
            return False
        
        # Add current request
        await self._redis.zadd(self._redis_key, {str(now): now})
        await self._redis.expire(self._redis_key, self.window_seconds)
        
        return True
    
    async def get_remaining(self) -> int:
        """Get the number of remaining requests in the current window."""
        if not self._redis:
            return self.max_requests
        
        now = datetime.utcnow().timestamp()
        window_start = now - self.window_seconds
        
        await self._redis.zremrangebyscore(self._redis_key, "-inf", window_start)
        current_count = await self._redis.zcard(self._redis_key)
        
        return max(0, self.max_requests - current_count)
    
    async def get_reset_time(self) -> Optional[float]:
        """Get the time when the rate limit resets."""
        if not self._redis:
            return None
        
        # Get the oldest entry in the window
        oldest = await self._redis.zrange(
            self._redis_key, 0, 0, withscores=True
        )
        
        if oldest:
            oldest_time = oldest[0][1]
            return oldest_time + self.window_seconds
        
        return None


# ==============================================================================
# FAILURE FINGERPRINT CACHE
# ==============================================================================

class FailureFingerprintCache:
    """
    Redis-backed cache for failure fingerprints.
    Prevents infinite repair loops by tracking seen failures.
    """
    
    KEY_PREFIX = "repair_engine:fingerprints"
    DEFAULT_TTL = 86400  # 24 hours
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self._redis = redis_client
    
    @classmethod
    async def create(cls) -> "FailureFingerprintCache":
        """Create a fingerprint cache."""
        pool = await RedisConnectionPool.get_instance()
        return cls(pool.client)
    
    async def has_fingerprint(self, fingerprint: str) -> bool:
        """Check if a fingerprint exists in the cache."""
        if not self._redis:
            return False
        
        return await self._redis.sismember(self.KEY_PREFIX, fingerprint)
    
    async def add_fingerprint(
        self,
        fingerprint: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Add a fingerprint to the cache."""
        if not self._redis:
            return
        
        await self._redis.sadd(self.KEY_PREFIX, fingerprint)
        
        if metadata:
            metadata_key = f"{self.KEY_PREFIX}:metadata:{fingerprint}"
            await self._redis.set(
                metadata_key,
                json.dumps(metadata),
                ex=self.DEFAULT_TTL
            )
    
    async def get_fingerprint_metadata(
        self,
        fingerprint: str,
    ) -> Optional[Dict[str, Any]]:
        """Get metadata for a fingerprint."""
        if not self._redis:
            return None
        
        metadata_key = f"{self.KEY_PREFIX}:metadata:{fingerprint}"
        data = await self._redis.get(metadata_key)
        
        return json.loads(data) if data else None
    
    async def remove_fingerprint(self, fingerprint: str) -> None:
        """Remove a fingerprint from the cache."""
        if not self._redis:
            return
        
        await self._redis.srem(self.KEY_PREFIX, fingerprint)
        
        metadata_key = f"{self.KEY_PREFIX}:metadata:{fingerprint}"
        await self._redis.delete(metadata_key)
    
    async def get_all_fingerprints(self) -> List[str]:
        """Get all fingerprints in the cache."""
        if not self._redis:
            return []
        
        return list(await self._redis.smembers(self.KEY_PREFIX))
    
    async def clear(self) -> None:
        """Clear all fingerprints."""
        if not self._redis:
            return
        
        # Get all related keys
        keys = [key async for key in self._redis.scan_iter(match=f"{self.KEY_PREFIX}*")]
        if keys:
            await self._redis.delete(*keys)
