"""
Health Check Module - Production Grade

Features:
- Liveness probe (is the process running?)
- Readiness probe (is the service ready to accept traffic?)
- Startup probe (has initial startup completed?)
- Deep health checks (LLM connectivity, disk, memory)
"""

import os
import time
import asyncio
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, UTC

from app.core.config import get_settings
from app.core.prompts import HEALTHCHECK_LLM_PING_PROMPT

logger = logging.getLogger("health")


# ==================================================
# Health Status
# ==================================================

class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


@dataclass
class HealthCheckResult:
    """Result of a single health check."""
    name: str
    status: HealthStatus
    message: Optional[str] = None
    latency_ms: Optional[float] = None
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "latency_ms": self.latency_ms,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class HealthReport:
    """Complete health report."""
    status: HealthStatus
    checks: Dict[str, HealthCheckResult]
    version: str
    environment: str
    uptime_seconds: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    
    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "checks": {k: v.to_dict() for k, v in self.checks.items()},
            "version": self.version,
            "environment": self.environment,
            "uptime_seconds": round(self.uptime_seconds, 2),
            "timestamp": self.timestamp.isoformat(),
        }


# ==================================================
# Health Checks
# ==================================================

class HealthChecker:
    """
    Production-grade health checker with multiple probe types.
    """
    
    _instance: Optional["HealthChecker"] = None
    
    @classmethod
    def get_instance(cls) -> "HealthChecker":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        self.settings = get_settings()
        self._start_time = time.time()
        self._startup_complete = False
        self._last_check: Optional[HealthReport] = None
        self._check_cache_seconds = 5  # Cache health checks for 5 seconds
    
    @property
    def uptime_seconds(self) -> float:
        return time.time() - self._start_time
    
    def mark_startup_complete(self):
        """Mark the service as having completed startup."""
        self._startup_complete = True
        logger.info("Startup complete")
    
    # --------------------------------------------------
    # Kubernetes Probes
    # --------------------------------------------------
    
    async def liveness_check(self) -> HealthReport:
        """
        Liveness probe - is the process alive and not deadlocked?
        
        Should be fast and simple. If this fails, Kubernetes will
        restart the container.
        """
        checks = {}
        
        # Simple alive check
        checks["process"] = HealthCheckResult(
            name="process",
            status=HealthStatus.HEALTHY,
            message="Process is running",
        )
        
        # Check for event loop health
        try:
            loop = asyncio.get_running_loop()
            checks["event_loop"] = HealthCheckResult(
                name="event_loop",
                status=HealthStatus.HEALTHY,
                message="Event loop is running",
                details={"is_running": loop.is_running()},
            )
        except RuntimeError:
            checks["event_loop"] = HealthCheckResult(
                name="event_loop",
                status=HealthStatus.UNHEALTHY,
                message="No running event loop",
            )
        
        overall_status = self._compute_overall_status(checks)
        
        return HealthReport(
            status=overall_status,
            checks=checks,
            version=self.settings.VERSION,
            environment=self.settings.ENV,
            uptime_seconds=self.uptime_seconds,
        )
    
    async def readiness_check(self) -> HealthReport:
        """
        Readiness probe - is the service ready to accept traffic?
        
        Checks all dependencies. If this fails, Kubernetes will
        stop sending traffic to this pod.
        """
        checks = {}
        
        # Check startup status
        if not self._startup_complete:
            checks["startup"] = HealthCheckResult(
                name="startup",
                status=HealthStatus.UNHEALTHY,
                message="Startup not complete",
            )
        else:
            checks["startup"] = HealthCheckResult(
                name="startup",
                status=HealthStatus.HEALTHY,
                message="Startup complete",
            )
        
        # Configuration gates needed to serve traffic
        checks["api_key"] = self._check_api_key()

        # External dependencies used by request handling
        checks["database"] = await self._check_database()
        checks["redis"] = await self._check_redis()
        
        # Check disk space
        checks["disk"] = self._check_disk_space()
        
        # Check memory
        checks["memory"] = self._check_memory()
        
        overall_status = self._compute_overall_status(checks)
        
        return HealthReport(
            status=overall_status,
            checks=checks,
            version=self.settings.VERSION,
            environment=self.settings.ENV,
            uptime_seconds=self.uptime_seconds,
        )
    
    async def startup_check(self) -> HealthReport:
        """
        Startup probe - has initial startup completed?
        
        Used during initial container startup. Kubernetes will
        wait for this to succeed before starting liveness/readiness.
        """
        checks = {}
        
        # Check configuration
        checks["config"] = self._check_configuration()
        
        # Check API key presence
        checks["api_key"] = self._check_api_key()
        
        overall_status = self._compute_overall_status(checks)
        
        return HealthReport(
            status=overall_status,
            checks=checks,
            version=self.settings.VERSION,
            environment=self.settings.ENV,
            uptime_seconds=self.uptime_seconds,
        )
    
    async def deep_check(self) -> HealthReport:
        """
        Deep health check - comprehensive system check.
        
        Used for detailed monitoring and debugging.
        """
        # Use cached result if recent
        if self._last_check:
            age = (datetime.now(UTC) - self._last_check.timestamp).total_seconds()
            if age < self._check_cache_seconds:
                return self._last_check
        
        checks = {}
        
        # All basic checks
        checks["config"] = self._check_configuration()
        checks["api_key"] = self._check_api_key()
        checks["disk"] = self._check_disk_space()
        checks["memory"] = self._check_memory()
        checks["llm"] = await self._check_llm_connectivity()
        
        # Additional deep checks
        checks["redis"] = await self._check_redis()
        checks["database"] = await self._check_database()
        
        overall_status = self._compute_overall_status(checks)
        
        report = HealthReport(
            status=overall_status,
            checks=checks,
            version=self.settings.VERSION,
            environment=self.settings.ENV,
            uptime_seconds=self.uptime_seconds,
        )
        
        self._last_check = report
        return report
    
    # --------------------------------------------------
    # Individual Health Checks
    # --------------------------------------------------
    
    def _check_configuration(self) -> HealthCheckResult:
        """Check if configuration is valid."""
        start = time.perf_counter()
        
        try:
            settings = get_settings()
            latency_ms = (time.perf_counter() - start) * 1000
            
            return HealthCheckResult(
                name="configuration",
                status=HealthStatus.HEALTHY,
                message="Configuration loaded successfully",
                latency_ms=latency_ms,
                details={
                    "environment": settings.ENV,
                    "version": settings.VERSION,
                },
            )
        except Exception as e:
            latency_ms = (time.perf_counter() - start) * 1000
            return HealthCheckResult(
                name="configuration",
                status=HealthStatus.UNHEALTHY,
                message=f"Configuration error: {str(e)}",
                latency_ms=latency_ms,
            )
    
    def _check_api_key(self) -> HealthCheckResult:
        """Check if API key is configured."""
        settings = get_settings()
        
        if settings.effective_api_keys:
            return HealthCheckResult(
                name="api_key",
                status=HealthStatus.HEALTHY,
                message="API key(s) configured",
                details={"key_count": len(settings.effective_api_keys)},
            )
        else:
            return HealthCheckResult(
                name="api_key",
                status=HealthStatus.UNHEALTHY,
                message="No API key configured",
            )
    
    def _check_disk_space(self) -> HealthCheckResult:
        """Check available disk space."""
        start = time.perf_counter()
        
        try:
            import shutil
            
            total, used, free = shutil.disk_usage("/")
            free_percent = (free / total) * 100
            latency_ms = (time.perf_counter() - start) * 1000
            
            if free_percent < 5:
                status = HealthStatus.UNHEALTHY
                message = f"Critical: Only {free_percent:.1f}% disk space free"
            elif free_percent < 15:
                status = HealthStatus.DEGRADED
                message = f"Warning: Only {free_percent:.1f}% disk space free"
            else:
                status = HealthStatus.HEALTHY
                message = f"{free_percent:.1f}% disk space free"
            
            return HealthCheckResult(
                name="disk",
                status=status,
                message=message,
                latency_ms=latency_ms,
                details={
                    "total_gb": round(total / (1024**3), 2),
                    "used_gb": round(used / (1024**3), 2),
                    "free_gb": round(free / (1024**3), 2),
                    "free_percent": round(free_percent, 2),
                },
            )
        except Exception as e:
            latency_ms = (time.perf_counter() - start) * 1000
            return HealthCheckResult(
                name="disk",
                status=HealthStatus.UNKNOWN,
                message=f"Unable to check disk space: {str(e)}",
                latency_ms=latency_ms,
            )
    
    def _check_memory(self) -> HealthCheckResult:
        """Check memory usage."""
        start = time.perf_counter()
        
        try:
            try:
                import psutil
                process = psutil.Process(os.getpid())
                memory_mb = process.memory_info().rss / (1024 * 1024)
                details = {
                    "memory_mb": round(memory_mb, 2),
                    "cpu_percent": process.cpu_percent(interval=None),
                }
            except ImportError:
                import resource
                usage = resource.getrusage(resource.RUSAGE_SELF)
                import sys
                if sys.platform == 'darwin':
                    memory_mb = usage.ru_maxrss / (1024 * 1024)
                else:
                    memory_mb = usage.ru_maxrss / 1024
                details = {
                    "memory_mb": round(memory_mb, 2),
                    "user_time_seconds": round(usage.ru_utime, 2),
                    "system_time_seconds": round(usage.ru_stime, 2),
                }
            
            latency_ms = (time.perf_counter() - start) * 1000
            
            # Assume 512MB as threshold (configurable)
            if memory_mb > 512:
                status = HealthStatus.DEGRADED
                message = f"High memory usage: {memory_mb:.1f}MB"
            else:
                status = HealthStatus.HEALTHY
                message = f"Memory usage: {memory_mb:.1f}MB"
            
            return HealthCheckResult(
                name="memory",
                status=status,
                message=message,
                latency_ms=latency_ms,
                details=details,
            )
        except Exception as e:
            latency_ms = (time.perf_counter() - start) * 1000
            return HealthCheckResult(
                name="memory",
                status=HealthStatus.UNKNOWN,
                message=f"Unable to check memory: {str(e)}",
                latency_ms=latency_ms,
            )
    
    async def _check_llm_connectivity(self) -> HealthCheckResult:
        """Check LLM API connectivity."""
        start = time.perf_counter()
        settings = get_settings()
        
        if not settings.effective_api_keys:
            return HealthCheckResult(
                name="llm",
                status=HealthStatus.UNHEALTHY,
                message="No API key configured",
            )
        
        try:
            # Import here to avoid circular dependency
            from google import genai
            
            client = genai.Client(api_key=settings.effective_api_keys[0])
            
            # Simple ping - list models
            loop = asyncio.get_running_loop()
            await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: client.models.generate_content(
                        model=settings.LLM_MODEL_NAME,
                        contents=HEALTHCHECK_LLM_PING_PROMPT,
                        config={"max_output_tokens": 1},
                    ),
                ),
                timeout=10.0,
            )
            
            latency_ms = (time.perf_counter() - start) * 1000
            
            return HealthCheckResult(
                name="llm",
                status=HealthStatus.HEALTHY,
                message="LLM API connected",
                latency_ms=latency_ms,
                details={"model": settings.LLM_MODEL_NAME},
            )
        except asyncio.TimeoutError:
            latency_ms = (time.perf_counter() - start) * 1000
            return HealthCheckResult(
                name="llm",
                status=HealthStatus.UNHEALTHY,
                message="LLM API timeout",
                latency_ms=latency_ms,
            )
        except Exception as e:
            latency_ms = (time.perf_counter() - start) * 1000
            return HealthCheckResult(
                name="llm",
                status=HealthStatus.UNHEALTHY,
                message=f"LLM API error: {str(e)}",
                latency_ms=latency_ms,
            )
    
    async def _check_redis(self) -> HealthCheckResult:
        """Check Redis connectivity (if configured)."""
        settings = get_settings()
        
        if not settings.REDIS_URL:
            return HealthCheckResult(
                name="redis",
                status=HealthStatus.HEALTHY,
                message="Redis not configured (optional)",
            )
        
        start = time.perf_counter()
        
        try:
            import redis.asyncio as redis
            
            client = redis.from_url(settings.REDIS_URL)
            await client.ping()
            await client.aclose()
            
            latency_ms = (time.perf_counter() - start) * 1000
            
            return HealthCheckResult(
                name="redis",
                status=HealthStatus.HEALTHY,
                message="Redis connected",
                latency_ms=latency_ms,
            )
        except ImportError:
            return HealthCheckResult(
                name="redis",
                status=HealthStatus.HEALTHY,
                message="Redis client not installed (optional)",
            )
        except Exception as e:
            latency_ms = (time.perf_counter() - start) * 1000
            return HealthCheckResult(
                name="redis",
                status=HealthStatus.UNHEALTHY,
                message=f"Redis error: {str(e)}",
                latency_ms=latency_ms,
            )
    
    async def _check_database(self) -> HealthCheckResult:
        """Check database connectivity (if configured)."""
        settings = get_settings()
        
        if not settings.MONGODB_URL:
            return HealthCheckResult(
                name="database",
                status=HealthStatus.HEALTHY,
                message="MongoDB not configured (using in-memory)",
            )
        
        start = time.perf_counter()
        try:
            from app.core.database import get_database
            db = get_database()
            await db.initialize()
            if db.storage_mode == "in-memory-fallback":
                latency_ms = (time.perf_counter() - start) * 1000
                return HealthCheckResult(
                    name="database",
                    status=HealthStatus.UNHEALTHY,
                    message="MongoDB unavailable; repository is running on in-memory fallback",
                    latency_ms=latency_ms,
                    details={"storage_mode": db.storage_mode, "error": db.last_error},
                )
            if db._client:
                await db._client.admin.command('ping')
                latency_ms = (time.perf_counter() - start) * 1000
                return HealthCheckResult(
                    name="database",
                    status=HealthStatus.HEALTHY,
                    message="MongoDB connected",
                    latency_ms=latency_ms,
                    details={"storage_mode": db.storage_mode},
                )
            else:
                return HealthCheckResult(
                    name="database",
                    status=HealthStatus.UNHEALTHY,
                    message="MongoDB client not initialized",
                    details={"storage_mode": db.storage_mode},
                )
        except Exception as e:
            latency_ms = (time.perf_counter() - start) * 1000
            return HealthCheckResult(
                name="database",
                status=HealthStatus.UNHEALTHY,
                message=f"MongoDB connection error: {str(e)}",
                latency_ms=latency_ms,
            )
    
    # --------------------------------------------------
    # Helpers
    # --------------------------------------------------
    
    @staticmethod
    def _compute_overall_status(checks: Dict[str, HealthCheckResult]) -> HealthStatus:
        """Compute overall health status from individual checks."""
        if not checks:
            return HealthStatus.UNKNOWN
        
        statuses = [c.status for c in checks.values()]
        
        if any(s == HealthStatus.UNHEALTHY for s in statuses):
            return HealthStatus.UNHEALTHY
        
        if any(s == HealthStatus.DEGRADED for s in statuses):
            return HealthStatus.DEGRADED
        
        if all(s == HealthStatus.HEALTHY for s in statuses):
            return HealthStatus.HEALTHY
        
        return HealthStatus.UNKNOWN


# ==================================================
# Convenience Functions
# ==================================================

def get_health_checker() -> HealthChecker:
    """Get the global health checker instance."""
    return HealthChecker.get_instance()
