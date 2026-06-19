import time
from threading import Lock

from prometheus_client import Counter, Gauge, Histogram, generate_latest


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
    REPORT_UPLOAD_COUNT = Counter(
        "report_upload_operations_total",
        "Total report upload operations completed",
    )
    REPORT_DOWNLOAD_COUNT = Counter(
        "report_download_operations_total",
        "Total report download operations completed",
    )
    TRACE_SAMPLED_COUNT = Counter(
        "trace_samples_total",
        "Total sampled traces",
    )
    ACTIVE_REQUESTS = Gauge(
        "http_requests_in_progress",
        "Active HTTP requests currently being processed",
    )
    MONGO_PING_DURATION = Histogram(
        "mongodb_ping_duration_seconds",
        "MongoDB ping duration in seconds",
    )

    _lock = Lock()
    _snapshot = {
        "requests_total": 0,
        "errors_total": 0,
        "report_uploads_total": 0,
        "report_downloads_total": 0,
        "traces_sampled_total": 0,
    }

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
            cls._snapshot["requests_total"] += 1

    @classmethod
    def record_error(cls, method: str, endpoint: str, status_code: int | str) -> None:
        cls.ERROR_COUNT.labels(
            method=method,
            endpoint=endpoint,
            status=str(status_code),
        ).inc()
        with cls._lock:
            cls._snapshot["errors_total"] += 1

    @classmethod
    def record_report_upload(cls) -> None:
        cls.REPORT_UPLOAD_COUNT.inc()
        with cls._lock:
            cls._snapshot["report_uploads_total"] += 1

    @classmethod
    def record_report_download(cls) -> None:
        cls.REPORT_DOWNLOAD_COUNT.inc()
        with cls._lock:
            cls._snapshot["report_downloads_total"] += 1

    @classmethod
    def record_trace_sampled(cls) -> None:
        cls.TRACE_SAMPLED_COUNT.inc()
        with cls._lock:
            cls._snapshot["traces_sampled_total"] += 1

    @classmethod
    def render_prometheus_metrics(cls) -> str:
        return generate_latest().decode("utf-8")

    @classmethod
    def get_metrics_snapshot(cls) -> dict:
        with cls._lock:
            snapshot = dict(cls._snapshot)
        snapshot["status"] = "active"
        snapshot["timestamp"] = time.time()
        return snapshot
