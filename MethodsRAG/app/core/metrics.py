import time
from threading import Lock

from prometheus_client import Counter, Histogram, generate_latest


class Metrics:
    REQUEST_COUNT = Counter(
        "http_requests_total",
        "Total HTTP requests",
        ["method", "endpoint", "status"],
    )
    REQUEST_DURATION = Histogram(
        "http_request_duration_seconds",
        "HTTP request duration in seconds",
        ["method", "endpoint"],
    )
    ERROR_COUNT = Counter(
        "app_errors_total",
        "Total application errors",
        ["method", "endpoint", "status"],
    )
    TRACE_SAMPLED_COUNT = Counter(
        "app_trace_sampled_total",
        "Total sampled traces",
    )
    SEARCH_COUNT = Counter(
        "rag_search_operations_total",
        "Total search operations completed",
    )
    UPLOAD_COUNT = Counter(
        "rag_upload_operations_total",
        "Total upload operations completed",
    )
    CACHE_HITS = Counter(
        "rag_cache_hits_total",
        "Total in-memory cache hits",
    )
    CACHE_MISSES = Counter(
        "rag_cache_misses_total",
        "Total in-memory cache misses",
    )

    _lock = Lock()
    _http_requests = 0
    _app_errors = 0
    _cache_hits = 0
    _cache_misses = 0

    @classmethod
    def record_request(
        cls,
        method: str,
        endpoint: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        cls.REQUEST_COUNT.labels(method=method, endpoint=endpoint, status=str(status_code)).inc()
        cls.REQUEST_DURATION.labels(method=method, endpoint=endpoint).observe(duration_seconds)
        with cls._lock:
            cls._http_requests += 1

    @classmethod
    def record_error(
        cls,
        method: str,
        endpoint: str,
        status_code: str,
    ) -> None:
        cls.ERROR_COUNT.labels(method=method, endpoint=endpoint, status=status_code).inc()
        with cls._lock:
            cls._app_errors += 1

    @classmethod
    def record_trace_sampled(cls) -> None:
        cls.TRACE_SAMPLED_COUNT.inc()

    @classmethod
    def record_cache_hit(cls) -> None:
        cls.CACHE_HITS.inc()
        with cls._lock:
            cls._cache_hits += 1

    @classmethod
    def record_cache_miss(cls) -> None:
        cls.CACHE_MISSES.inc()
        with cls._lock:
            cls._cache_misses += 1

    @classmethod
    def render_prometheus_metrics(cls) -> str:
        return generate_latest().decode("utf-8")

    @classmethod
    def get_metrics_snapshot(cls) -> dict:
        with cls._lock:
            return {
                "status": "active",
                "timestamp": time.time(),
                "http_requests": cls._http_requests,
                "application_errors": cls._app_errors,
                "cache_hits": cls._cache_hits,
                "cache_misses": cls._cache_misses,
            }
