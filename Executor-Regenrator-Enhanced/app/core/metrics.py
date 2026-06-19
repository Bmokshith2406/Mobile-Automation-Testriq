"""
Observability Module - Production Grade Metrics

Features:
- Prometheus metrics
- Request/response tracking
- LLM call monitoring
- Repair pipeline metrics
- System health metrics
"""

import time
import functools
import logging
from typing import Callable, Optional, Dict, Any
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock

logger = logging.getLogger("metrics")


# ==================================================
# Metric Types (Prometheus-compatible)
# ==================================================

class MetricType(str, Enum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"


@dataclass
class MetricValue:
    """Stores metric value with labels."""
    value: float = 0.0
    labels: Dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class Counter:
    """
    Prometheus-style counter metric.
    Only increments, never decreases.
    """
    
    def __init__(self, name: str, description: str, labels: Optional[list] = None):
        self.name = name
        self.description = description
        self.label_names = labels or []
        self._values: Dict[tuple, float] = {}
        self._lock = Lock()
    
    def inc(self, value: float = 1.0, **labels):
        """Increment the counter."""
        key = self._make_key(labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + value
    
    def _make_key(self, labels: dict) -> tuple:
        return tuple(sorted(labels.items()))
    
    def collect(self) -> list:
        """Collect all values for export."""
        with self._lock:
            return [
                {"labels": dict(key), "value": value}
                for key, value in self._values.items()
            ]


class Gauge:
    """
    Prometheus-style gauge metric.
    Can increase and decrease.
    """
    
    def __init__(self, name: str, description: str, labels: Optional[list] = None):
        self.name = name
        self.description = description
        self.label_names = labels or []
        self._values: Dict[tuple, float] = {}
        self._lock = Lock()
    
    def set(self, value: float, **labels):
        """Set the gauge value."""
        key = self._make_key(labels)
        with self._lock:
            self._values[key] = value
    
    def inc(self, value: float = 1.0, **labels):
        """Increment the gauge."""
        key = self._make_key(labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + value
    
    def dec(self, value: float = 1.0, **labels):
        """Decrement the gauge."""
        key = self._make_key(labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) - value
    
    def _make_key(self, labels: dict) -> tuple:
        return tuple(sorted(labels.items()))
    
    def collect(self) -> list:
        with self._lock:
            return [
                {"labels": dict(key), "value": value}
                for key, value in self._values.items()
            ]


class Histogram:
    """
    Prometheus-style histogram metric.
    Tracks value distributions.
    """
    
    DEFAULT_BUCKETS = (
        0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5,
        0.75, 1.0, 2.5, 5.0, 7.5, 10.0, float("inf")
    )
    
    def __init__(
        self,
        name: str,
        description: str,
        labels: Optional[list] = None,
        buckets: Optional[tuple] = None,
    ):
        self.name = name
        self.description = description
        self.label_names = labels or []
        self.buckets = buckets or self.DEFAULT_BUCKETS
        self._values: Dict[tuple, Dict[str, float]] = {}
        self._lock = Lock()
    
    def observe(self, value: float, **labels):
        """Record an observation."""
        key = self._make_key(labels)
        with self._lock:
            if key not in self._values:
                self._values[key] = {
                    "sum": 0.0,
                    "count": 0,
                    "buckets": {b: 0 for b in self.buckets},
                }
            
            data = self._values[key]
            data["sum"] += value
            data["count"] += 1
            
            for bucket in self.buckets:
                if value <= bucket:
                    data["buckets"][bucket] += 1
    
    def _make_key(self, labels: dict) -> tuple:
        return tuple(sorted(labels.items()))
    
    @contextmanager
    def time(self, **labels):
        """Context manager to time a block of code."""
        start = time.perf_counter()
        try:
            yield
        finally:
            self.observe(time.perf_counter() - start, **labels)
    
    def collect(self) -> list:
        with self._lock:
            return [
                {
                    "labels": dict(key),
                    "sum": data["sum"],
                    "count": data["count"],
                    "buckets": dict(data["buckets"]),
                }
                for key, data in self._values.items()
            ]


# ==================================================
# Application Metrics Registry
# ==================================================

class MetricsRegistry:
    """
    Central registry for all application metrics.
    """
    
    _instance: Optional["MetricsRegistry"] = None
    
    @classmethod
    def get_instance(cls) -> "MetricsRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        if MetricsRegistry._instance is not None:
            raise RuntimeError("MetricsRegistry is a singleton")
        
        # Request metrics
        self.http_requests_total = Counter(
            "http_requests_total",
            "Total HTTP requests",
            labels=["method", "path", "status"]
        )
        
        self.http_request_duration_seconds = Histogram(
            "http_request_duration_seconds",
            "HTTP request duration in seconds",
            labels=["method", "path"]
        )
        
        self.http_requests_in_progress = Gauge(
            "http_requests_in_progress",
            "HTTP requests currently being processed",
            labels=["method", "path"]
        )
        
        # Repair metrics
        self.repair_requests_total = Counter(
            "repair_requests_total",
            "Total repair requests",
            labels=["outcome", "action_type"]
        )
        
        self.repair_duration_seconds = Histogram(
            "repair_duration_seconds",
            "Repair operation duration in seconds",
            labels=["outcome"]
        )
        
        self.repair_pipeline_stage_duration = Histogram(
            "repair_pipeline_stage_duration_seconds",
            "Duration of each repair pipeline stage",
            labels=["stage"]
        )
        
        # LLM metrics
        self.llm_calls_total = Counter(
            "llm_calls_total",
            "Total LLM API calls",
            labels=["role", "mode", "status"]
        )
        
        self.llm_call_duration_seconds = Histogram(
            "llm_call_duration_seconds",
            "LLM API call duration in seconds",
            labels=["role", "mode"]
        )
        
        self.llm_tokens_total = Counter(
            "llm_tokens_total",
            "Total LLM tokens used",
            labels=["role", "type"]  # type: prompt or completion
        )
        
        self.llm_errors_total = Counter(
            "llm_errors_total",
            "Total LLM errors",
            labels=["role", "error_type"]
        )
        
        # Execution metrics
        self.script_executions_total = Counter(
            "script_executions_total",
            "Total script executions",
            labels=["status"]  # passed, failed, timeout
        )
        
        self.script_execution_duration_seconds = Histogram(
            "script_execution_duration_seconds",
            "Script execution duration in seconds",
            labels=["status"]
        )
        
        self.self_healing_attempts_total = Counter(
            "self_healing_attempts_total",
            "Total self-healing repair attempts",
            labels=["outcome"]
        )
        
        # Circuit breaker metrics
        self.circuit_breaker_state = Gauge(
            "circuit_breaker_state",
            "Circuit breaker state (0=closed, 1=open)",
            labels=["name"]
        )
        
        self.circuit_breaker_failures = Counter(
            "circuit_breaker_failures_total",
            "Total circuit breaker recorded failures",
            labels=["name"]
        )
        
        # Rate limiting metrics
        self.rate_limit_exceeded_total = Counter(
            "rate_limit_exceeded_total",
            "Total rate limit exceeded events",
            labels=["client_type"]
        )
        
        # System metrics
        self.active_connections = Gauge(
            "active_connections",
            "Number of active connections"
        )
        
        MetricsRegistry._instance = self
    
    def export_prometheus(self) -> str:
        """
        Export all metrics in Prometheus text format.
        """
        lines = []
        
        for attr_name in dir(self):
            attr = getattr(self, attr_name)
            
            if isinstance(attr, Counter):
                lines.append(f"# HELP {attr.name} {attr.description}")
                lines.append(f"# TYPE {attr.name} counter")
                for item in attr.collect():
                    labels_str = self._format_labels(item["labels"])
                    lines.append(f"{attr.name}{labels_str} {item['value']}")
            
            elif isinstance(attr, Gauge):
                lines.append(f"# HELP {attr.name} {attr.description}")
                lines.append(f"# TYPE {attr.name} gauge")
                for item in attr.collect():
                    labels_str = self._format_labels(item["labels"])
                    lines.append(f"{attr.name}{labels_str} {item['value']}")
            
            elif isinstance(attr, Histogram):
                lines.append(f"# HELP {attr.name} {attr.description}")
                lines.append(f"# TYPE {attr.name} histogram")
                for item in attr.collect():
                    labels_str = self._format_labels(item["labels"])
                    for bucket, count in item["buckets"].items():
                        le = "+Inf" if bucket == float("inf") else str(bucket)
                        lines.append(f'{attr.name}_bucket{{le="{le}"{labels_str[1:]}}} {count}')
                    lines.append(f"{attr.name}_sum{labels_str} {item['sum']}")
                    lines.append(f"{attr.name}_count{labels_str} {item['count']}")
        
        return "\n".join(lines)
    
    @staticmethod
    def _format_labels(labels: dict) -> str:
        if not labels:
            return ""
        parts = [f'{k}="{v}"' for k, v in labels.items()]
        return "{" + ",".join(parts) + "}"


# ==================================================
# Metric Decorators
# ==================================================

def track_time(histogram: Histogram, **static_labels):
    """
    Decorator to track function execution time.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            with histogram.time(**static_labels):
                return await func(*args, **kwargs)
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            with histogram.time(**static_labels):
                return func(*args, **kwargs)
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


def count_calls(counter: Counter, **static_labels):
    """
    Decorator to count function calls.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                result = await func(*args, **kwargs)
                counter.inc(status="success", **static_labels)
                return result
            except Exception:
                counter.inc(status="error", **static_labels)
                raise
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                result = func(*args, **kwargs)
                counter.inc(status="success", **static_labels)
                return result
            except Exception:
                counter.inc(status="error", **static_labels)
                raise
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


# ==================================================
# Convenience Functions
# ==================================================

def get_metrics() -> MetricsRegistry:
    """Get the global metrics registry."""
    return MetricsRegistry.get_instance()


# Need to import asyncio for decorator
import asyncio
