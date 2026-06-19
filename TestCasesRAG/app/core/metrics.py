"""
Operational metrics for request monitoring, business events, and Prometheus export.
"""

from collections import defaultdict
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Dict, Tuple
import time

from app.core.logging import logger

_metrics_lock = Lock()

_metrics = {
    "http_requests_total": defaultdict(int),
    "http_request_duration_seconds": defaultdict(list),
    "http_errors_total": defaultdict(int),
    "search_results_count": [],
    "upload_documents_count": [],
    "cache_hits": 0,
    "cache_misses": 0,
    "traces_sampled": 0,
    "background_jobs_total": defaultdict(int),
}


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _labels_to_text(labels: Dict[str, Any]) -> str:
    escaped = []
    for key, value in labels.items():
        safe_value = str(value).replace("\\", "\\\\").replace('"', '\\"')
        escaped.append(f'{key}="{safe_value}"')
    return ",".join(escaped)


class Metrics:
    """Thread-safe in-process metrics registry."""

    @staticmethod
    def record_request(
        method: str,
        path: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        try:
            request_key: Tuple[str, str, str] = (
                str(method or "UNKNOWN").upper(),
                str(path or "/"),
                str(status_code),
            )
            duration_key: Tuple[str, str] = (
                str(method or "UNKNOWN").upper(),
                str(path or "/"),
            )

            with _metrics_lock:
                _metrics["http_requests_total"][request_key] += 1
                _metrics["http_request_duration_seconds"][duration_key].append(
                    float(duration_seconds or 0.0)
                )

        except Exception as err:
            logger.debug("metrics_record_request_failed", extra={"error": str(err)})

    @staticmethod
    def record_error(method: str, path: str, error_code: str) -> None:
        try:
            key: Tuple[str, str, str] = (
                str(method or "UNKNOWN").upper(),
                str(path or "/"),
                str(error_code or "unknown"),
            )
            with _metrics_lock:
                _metrics["http_errors_total"][key] += 1
        except Exception as err:
            logger.debug("metrics_record_error_failed", extra={"error": str(err)})

    @staticmethod
    def record_search(results_count: int) -> None:
        try:
            with _metrics_lock:
                _metrics["search_results_count"].append(int(results_count or 0))
        except Exception:
            pass

    @staticmethod
    def record_upload(document_count: int) -> None:
        try:
            with _metrics_lock:
                _metrics["upload_documents_count"].append(int(document_count or 0))
        except Exception:
            pass

    @staticmethod
    def record_cache_hit() -> None:
        try:
            with _metrics_lock:
                _metrics["cache_hits"] += 1
        except Exception:
            pass

    @staticmethod
    def record_cache_miss() -> None:
        try:
            with _metrics_lock:
                _metrics["cache_misses"] += 1
        except Exception:
            pass

    @staticmethod
    def record_trace_sampled() -> None:
        try:
            with _metrics_lock:
                _metrics["traces_sampled"] += 1
        except Exception:
            pass

    @staticmethod
    def record_background_job(status: str) -> None:
        try:
            safe_status = str(status or "unknown").lower()
            with _metrics_lock:
                _metrics["background_jobs_total"][safe_status] += 1
        except Exception:
            pass

    @staticmethod
    def get_metrics_snapshot() -> Dict[str, Any]:
        try:
            with _metrics_lock:
                request_counts = dict(_metrics["http_requests_total"])
                error_counts = dict(_metrics["http_errors_total"])
                latency_data = dict(_metrics["http_request_duration_seconds"])
                search_results = list(_metrics["search_results_count"])
                upload_docs = list(_metrics["upload_documents_count"])
                cache_hits = _metrics["cache_hits"]
                cache_misses = _metrics["cache_misses"]
                traces_sampled = _metrics["traces_sampled"]
                background_jobs = dict(_metrics["background_jobs_total"])
        except Exception as err:
            logger.error("metrics_snapshot_failed", extra={"error": str(err)})
            return {
                "timestamp": _utc_timestamp(),
                "error": "metrics_collection_failed",
            }

        request_stats: Dict[str, Any] = {}
        for (method, path, status_code), count in request_counts.items():
            key = f"{method} {path} {status_code}"
            durations = latency_data.get((method, path), [])
            avg_ms = (sum(durations) / len(durations) * 1000) if durations else 0.0
            request_stats[key] = {
                "count": count,
                "avg_ms": round(avg_ms, 2),
            }

        error_stats = {
            f"{method} {path} {error_code}": count
            for (method, path, error_code), count in error_counts.items()
        }

        cache_total = cache_hits + cache_misses

        return {
            "timestamp": _utc_timestamp(),
            "http_requests": request_stats,
            "http_errors": error_stats,
            "search": {
                "total_operations": len(search_results),
                "avg_results": (
                    sum(search_results) / len(search_results)
                    if search_results else 0
                ),
            },
            "upload": {
                "total_operations": len(upload_docs),
                "total_documents": sum(upload_docs),
            },
            "cache": {
                "hits": cache_hits,
                "misses": cache_misses,
                "hit_rate": (cache_hits / cache_total) if cache_total else 0.0,
            },
            "tracing": {
                "sampled_requests": traces_sampled,
            },
            "background_jobs": background_jobs,
        }

    @staticmethod
    def render_prometheus_metrics() -> str:
        try:
            with _metrics_lock:
                request_counts = dict(_metrics["http_requests_total"])
                error_counts = dict(_metrics["http_errors_total"])
                latency_data = dict(_metrics["http_request_duration_seconds"])
                search_results = list(_metrics["search_results_count"])
                upload_docs = list(_metrics["upload_documents_count"])
                cache_hits = _metrics["cache_hits"]
                cache_misses = _metrics["cache_misses"]
                traces_sampled = _metrics["traces_sampled"]
                background_jobs = dict(_metrics["background_jobs_total"])
        except Exception as err:
            logger.error("metrics_prometheus_render_failed", extra={"error": str(err)})
            raise

        lines = [
            "# HELP testcase_http_requests_total Total HTTP requests handled.",
            "# TYPE testcase_http_requests_total counter",
        ]
        for (method, path, status_code), count in sorted(request_counts.items()):
            labels = _labels_to_text(
                {"method": method, "path": path, "status_code": status_code}
            )
            lines.append(f"testcase_http_requests_total{{{labels}}} {count}")

        lines.extend([
            "# HELP testcase_http_request_duration_seconds_avg Average HTTP request duration in seconds.",
            "# TYPE testcase_http_request_duration_seconds_avg gauge",
        ])
        for (method, path), durations in sorted(latency_data.items()):
            avg_seconds = (sum(durations) / len(durations)) if durations else 0.0
            labels = _labels_to_text({"method": method, "path": path})
            lines.append(
                f"testcase_http_request_duration_seconds_avg{{{labels}}} {avg_seconds}"
            )

        lines.extend([
            "# HELP testcase_http_errors_total Total HTTP errors observed.",
            "# TYPE testcase_http_errors_total counter",
        ])
        for (method, path, error_code), count in sorted(error_counts.items()):
            labels = _labels_to_text(
                {"method": method, "path": path, "error_code": error_code}
            )
            lines.append(f"testcase_http_errors_total{{{labels}}} {count}")

        lines.extend([
            "# HELP testcase_search_operations_total Total search operations completed.",
            "# TYPE testcase_search_operations_total counter",
            f"testcase_search_operations_total {len(search_results)}",
            "# HELP testcase_search_results_avg Average number of search results returned.",
            "# TYPE testcase_search_results_avg gauge",
            (
                f"testcase_search_results_avg "
                f"{(sum(search_results) / len(search_results)) if search_results else 0.0}"
            ),
            "# HELP testcase_upload_operations_total Total upload operations completed.",
            "# TYPE testcase_upload_operations_total counter",
            f"testcase_upload_operations_total {len(upload_docs)}",
            "# HELP testcase_upload_documents_total Total uploaded testcase documents.",
            "# TYPE testcase_upload_documents_total counter",
            f"testcase_upload_documents_total {sum(upload_docs)}",
            "# HELP testcase_cache_hits_total Search cache hits.",
            "# TYPE testcase_cache_hits_total counter",
            f"testcase_cache_hits_total {cache_hits}",
            "# HELP testcase_cache_misses_total Search cache misses.",
            "# TYPE testcase_cache_misses_total counter",
            f"testcase_cache_misses_total {cache_misses}",
            "# HELP testcase_traces_sampled_total Requests sampled for tracing.",
            "# TYPE testcase_traces_sampled_total counter",
            f"testcase_traces_sampled_total {traces_sampled}",
        ])

        lines.extend([
            "# HELP testcase_background_jobs_total Background ingestion jobs by status.",
            "# TYPE testcase_background_jobs_total counter",
        ])
        for status, count in sorted(background_jobs.items()):
            labels = _labels_to_text({"status": status})
            lines.append(f"testcase_background_jobs_total{{{labels}}} {count}")

        return "\n".join(lines) + "\n"


class RequestTimer:
    """Context manager for timing requests or service calls."""

    def __init__(self, method: str, path: str):
        self.method = method
        self.path = path
        self.start_time = None
        self.duration = None

    def __enter__(self):
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time is not None:
            self.duration = time.perf_counter() - self.start_time
        return False

    async def __aenter__(self):
        self.start_time = time.perf_counter()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.start_time is not None:
            self.duration = time.perf_counter() - self.start_time
        return False
