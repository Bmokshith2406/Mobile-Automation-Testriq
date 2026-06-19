# app/core/metrics.py
"""
Metrics Collection System

Provides application-wide metrics for monitoring and observability.
"""

import bisect
import time
import threading
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from collections import defaultdict

from app.core.config import get_settings


@dataclass
class Counter:
    """Thread-safe counter metric."""
    value: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)
    
    def increment(self, amount: int = 1) -> None:
        with self._lock:
            self.value += amount
    
    def reset(self) -> int:
        with self._lock:
            old_value = self.value
            self.value = 0
            return old_value


@dataclass
class Gauge:
    """Thread-safe gauge metric."""
    value: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock)
    
    def set(self, value: float) -> None:
        with self._lock:
            self.value = value
    
    def increment(self, amount: float = 1.0) -> None:
        with self._lock:
            self.value += amount
    
    def decrement(self, amount: float = 1.0) -> None:
        with self._lock:
            self.value -= amount


@dataclass
class Histogram:
    """Thread-safe histogram with O(log n) insert and O(1) percentile reads.

    Maintains a pre-sorted list via bisect so get_stats() never needs to sort.
    """
    _sorted_values: list = field(default_factory=list)
    _sum: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _max_samples: int = 1000

    def observe(self, value: float) -> None:
        with self._lock:
            bisect.insort(self._sorted_values, value)
            self._sum += value
            if len(self._sorted_values) > self._max_samples:
                removed = self._sorted_values.pop(0)
                self._sum -= removed

    def get_stats(self) -> Dict[str, float]:
        with self._lock:
            count = len(self._sorted_values)
            if count == 0:
                return {
                    "count": 0,
                    "sum": 0.0,
                    "mean": 0.0,
                    "min": 0.0,
                    "max": 0.0,
                    "p50": 0.0,
                    "p90": 0.0,
                    "p99": 0.0,
                }
            sv = self._sorted_values
            return {
                "count": count,
                "sum": round(self._sum, 4),
                "mean": round(self._sum / count, 4),
                "min": sv[0],
                "max": sv[-1],
                "p50": sv[int(count * 0.50)],
                "p90": sv[int(count * 0.90)],
                "p99": sv[min(int(count * 0.99), count - 1)],
            }


class MetricsRegistry:
    """
    Central metrics registry.
    
    Collects and exposes application metrics.
    """
    
    def __init__(self):
        self._start_time = time.time()
        
        # Request metrics
        self.requests_total = Counter()
        self.requests_success = Counter()
        self.requests_failed = Counter()
        self.requests_in_progress = Gauge()
        self.request_duration_ms = Histogram()
        
        # LLM metrics
        self.llm_calls_total = Counter()
        self.llm_calls_success = Counter()
        self.llm_calls_failed = Counter()
        self.llm_calls_cached = Counter()
        self.llm_tokens_input = Counter()
        self.llm_tokens_output = Counter()
        self.llm_duration_ms = Histogram()
        
        # CIR metrics
        self.cir_builds_total = Counter()
        self.cir_builds_success = Counter()
        self.cir_builds_failed = Counter()
        self.cir_build_duration_ms = Histogram()
        
        # Generator metrics
        self.scripts_generated = Counter()
        self.script_size_bytes = Histogram()
        
        # Error tracking
        self.errors_by_type: Dict[str, Counter] = defaultdict(Counter)
    
    def record_request_start(self) -> None:
        """Record start of a request."""
        self.requests_total.increment()
        self.requests_in_progress.increment()
    
    def record_request_end(self, success: bool, duration_ms: float) -> None:
        """Record end of a request."""
        self.requests_in_progress.decrement()
        self.request_duration_ms.observe(duration_ms)
        
        if success:
            self.requests_success.increment()
        else:
            self.requests_failed.increment()
    
    def record_llm_call(
        self,
        success: bool,
        duration_ms: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cached: bool = False,
    ) -> None:
        """Record an LLM call."""
        self.llm_calls_total.increment()
        self.llm_duration_ms.observe(duration_ms)
        
        if cached:
            self.llm_calls_cached.increment()
        
        if success:
            self.llm_calls_success.increment()
            self.llm_tokens_input.increment(input_tokens)
            self.llm_tokens_output.increment(output_tokens)
        else:
            self.llm_calls_failed.increment()
    
    def record_error(self, error_type: str) -> None:
        """Record an error by type."""
        self.errors_by_type[error_type].increment()
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get all metrics as a dictionary."""
        uptime_seconds = time.time() - self._start_time
        
        return {
            "uptime_seconds": round(uptime_seconds, 2),
            "requests": {
                "total": self.requests_total.value,
                "success": self.requests_success.value,
                "failed": self.requests_failed.value,
                "in_progress": int(self.requests_in_progress.value),
                "duration_ms": self.request_duration_ms.get_stats(),
            },
            "llm": {
                "calls_total": self.llm_calls_total.value,
                "calls_success": self.llm_calls_success.value,
                "calls_failed": self.llm_calls_failed.value,
                "calls_cached": self.llm_calls_cached.value,
                "tokens_input": self.llm_tokens_input.value,
                "tokens_output": self.llm_tokens_output.value,
                "tokens_total": self.llm_tokens_input.value + self.llm_tokens_output.value,
                "duration_ms": self.llm_duration_ms.get_stats(),
            },
            "cir": {
                "builds_total": self.cir_builds_total.value,
                "builds_success": self.cir_builds_success.value,
                "builds_failed": self.cir_builds_failed.value,
                "build_duration_ms": self.cir_build_duration_ms.get_stats(),
            },
            "generator": {
                "scripts_generated": self.scripts_generated.value,
                "script_size_bytes": self.script_size_bytes.get_stats(),
            },
            "errors": {
                error_type: counter.value
                for error_type, counter in self.errors_by_type.items()
            },
        }


# Global metrics registry
_metrics: Optional[MetricsRegistry] = None


def get_metrics() -> MetricsRegistry:
    """Get or create the global metrics registry."""
    global _metrics
    
    if _metrics is None:
        _metrics = MetricsRegistry()
    
    return _metrics

