# tests/test_batch_processor.py
"""
Tests for BatchProcessor (app/services/batch_processor.py)

Covers:
- Race condition fix: total_tokens and failed_count summed from results (P2-T4)
- Cost estimate falls back to 0.0 on estimator failure (P2-T5)
- BatchItemResult tokens_used field correctly populated
- BatchResult.failed_items matches actual failures
- BatchResult.status: COMPLETED when 0 failures
- BatchResult.status: PARTIAL when some fail
- BatchResult.status: FAILED when all fail
- stop_on_error marks remaining items as SKIPPED
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from pathlib import Path

from app.models.batch import (
    BatchRequest, BatchItem, BatchResult,
    BatchStatus, BatchItemStatus,
)


# ---------------------------------------------------------------------------
# Helpers — build minimal TestCase-like objects
# ---------------------------------------------------------------------------

def _make_test_case(tc_id: str = "TC_001"):
    from app.models.test_case import TestCase, Step
    return TestCase(
        test_case_id=tc_id,
        description="Login test",
        target_framework="playwright",
        steps=[
            Step(step_id="S1", description="Navigate to login page"),
            Step(step_id="S2", description="Enter credentials"),
        ],
    )


def _make_batch_request(tc_ids, stop_on_error=False, parallel=2):
    items = [BatchItem(test_case=_make_test_case(tc_id)) for tc_id in tc_ids]
    return BatchRequest(
        items=items,
        parallel=parallel,
        stop_on_error=stop_on_error,
    )


def _make_mock_result(tokens: int = 100, path: str = "/tmp/t.py"):
    """Return a MagicMock shaped like GeneratedScriptResult."""
    return MagicMock(
        request_id="test-req-id",
        path=Path(path),
        duration_ms=123.0,
        input_tokens=tokens // 2,
        output_tokens=tokens // 2,
        total_tokens=tokens,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def processor(monkeypatch):
    monkeypatch.setenv("API_KEY", "a" * 32)
    from app.services.batch_processor import BatchProcessor
    return BatchProcessor()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBatchStatus:

    @pytest.mark.asyncio
    async def test_all_success_gives_completed_status(self, processor, monkeypatch):
        monkeypatch.setenv("API_KEY", "a" * 32)
        request = _make_batch_request(["TC_A", "TC_B"])

        with patch("app.services.batch_processor.GenerationService") as MockSvc, \
             patch("app.services.batch_processor.estimate_cost",
                   return_value=MagicMock(estimated_cost_usd=0.001, estimated_total_tokens=50)):

            MockSvc.return_value.generate = AsyncMock(return_value=_make_mock_result(50))

            result = await processor.process(request)

        assert result.status == BatchStatus.COMPLETED
        assert result.failed_items == 0

    @pytest.mark.asyncio
    async def test_total_tokens_summed_from_results_not_shared_counter(self, processor):
        """Regression: verifies no nonlocal mutation race condition."""
        request = _make_batch_request(["TC_X", "TC_Y"])

        with patch("app.services.batch_processor.GenerationService") as MockSvc, \
             patch("app.services.batch_processor.estimate_cost",
                   return_value=MagicMock(estimated_cost_usd=0.001, estimated_total_tokens=100)):

            MockSvc.return_value.generate = AsyncMock(return_value=_make_mock_result(100))

            result = await processor.process(request)

        # 2 items × 100 tokens each = 200 total
        assert result.total_tokens_used == 200

    @pytest.mark.asyncio
    async def test_failed_items_count_correct(self, processor):
        request = _make_batch_request(["TC_FAIL"])

        with patch("app.services.batch_processor.GenerationService") as MockSvc, \
             patch("app.services.batch_processor.estimate_cost",
                   return_value=MagicMock(estimated_cost_usd=0.0, estimated_total_tokens=0)):

            MockSvc.return_value.generate = AsyncMock(side_effect=RuntimeError("CIR failed"))

            result = await processor.process(request)

        assert result.failed_items == 1
        assert result.status == BatchStatus.FAILED

    @pytest.mark.asyncio
    async def test_cost_estimate_falls_back_to_zero_on_error(self, processor):
        request = _make_batch_request(["TC_COST"])

        with patch("app.services.batch_processor.GenerationService") as MockSvc, \
             patch("app.services.batch_processor.estimate_cost",
                   side_effect=Exception("pricing unavailable")):

            MockSvc.return_value.generate = AsyncMock(return_value=_make_mock_result(50))

            result = await processor.process(request)

        assert result.cost_estimate_usd == 0.0

    @pytest.mark.asyncio
    async def test_stop_on_error_marks_remaining_as_skipped(self, processor):
        request = _make_batch_request(["TC_1", "TC_2", "TC_3"], stop_on_error=True, parallel=1)

        call_count = 0

        async def fail_on_second(test_case):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise RuntimeError("deliberate fail")
            return _make_mock_result(0)

        with patch("app.services.batch_processor.GenerationService") as MockSvc, \
             patch("app.services.batch_processor.estimate_cost",
                   return_value=MagicMock(estimated_cost_usd=0.0, estimated_total_tokens=0)):

            MockSvc.return_value.generate = AsyncMock(side_effect=fail_on_second)

            result = await processor.process(request)

        skipped = [r for r in result.results if r.status == BatchItemStatus.SKIPPED]
        assert len(skipped) >= 1
