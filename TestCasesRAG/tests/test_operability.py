import pytest

from app.core.cache import get_search_cache, invalidate_search_cache, set_search_cache
from app.core.cache_layer import cache_manager
from app.core.config import Settings, validate_startup_settings
from app.core.metrics import Metrics


class TestStartupValidation:
    def test_validate_startup_settings_rejects_invalid_config(self):
        settings = Settings()
        settings.MONGO_CONNECTION_STRING = ""
        settings.CORS_ALLOWED_ORIGINS = []
        settings.CACHE_BACKEND = "redis"
        settings.REDIS_URL = None
        settings.TRACE_SAMPLE_RATE = 2
        settings.INGESTION_WORKER_COUNT = 0
        settings.ENABLE_TRACING = True

        errors = validate_startup_settings(settings)

        assert any("MONGO_CONNECTION_STRING" in error for error in errors)
        assert any("CORS_ALLOWED_ORIGINS" in error for error in errors)
        assert any("REDIS_URL" in error for error in errors)
        assert any("TRACE_SAMPLE_RATE" in error for error in errors)
        assert any("INGESTION_WORKER_COUNT" in error for error in errors)


class TestCacheInvalidation:
    @pytest.mark.asyncio
    async def test_search_cache_invalidation_bumps_namespace(self):
        await cache_manager.clear()

        await set_search_cache("login-query", {"results_count": 1})
        cached = await get_search_cache("login-query")
        assert cached == {"results_count": 1}

        await invalidate_search_cache(reason="test")
        invalidated = await get_search_cache("login-query")
        assert invalidated is None


class TestMetricsExport:
    def test_prometheus_export_contains_request_counter(self):
        Metrics.record_request("GET", "/health", 200, 0.01)
        Metrics.record_error("GET", "/health", "500")
        Metrics.record_search(3)
        Metrics.record_upload(2)
        Metrics.record_cache_hit()
        Metrics.record_trace_sampled()
        Metrics.record_background_job("queued")

        payload = Metrics.render_prometheus_metrics()

        assert 'testcase_http_requests_total{method="GET",path="/health",status_code="200"}' in payload
        assert 'testcase_http_errors_total{method="GET",path="/health",error_code="500"}' in payload
        assert "testcase_search_operations_total" in payload
        assert "testcase_background_jobs_total{status=\"queued\"}" in payload
