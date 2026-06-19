from prometheus_client import Counter, Histogram

# ==============================
# Metrics (Prometheus)
# ==============================
REQUEST_COUNT = Counter(
    "orchestrator_requests_total", "Total orchestrator /run requests", ["stage", "status"]
)
REQUEST_DURATION = Histogram(
    "orchestrator_request_duration_seconds", "Duration of /run pipeline", ["stage"]
)
DOWNSTREAM_RETRIES = Counter(
    "orchestrator_downstream_retries_total", "Total retries to downstream services", ["service"]
)
DOWNSTREAM_FAILURES = Counter(
    "orchestrator_downstream_failures_total", "Downstream permanent failures", ["service"]
)
