# app/services/batch_processor.py
"""
Batch Processing Service

Handles parallel processing of multiple test cases.
"""

import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Callable, Dict, Any
import logging

from app.models.batch import (
    BatchRequest,
    BatchResult,
    BatchItemResult,
    BatchProgress,
    BatchStatus,
    BatchItemStatus,
)
from app.services.generation_service import GenerationService
from app.core.cost_estimator import estimate_cost
from app.core.metrics import get_metrics
from app.core.config import get_settings

logger = logging.getLogger("batch_processor")


class BatchProcessor:
    """
    Processes multiple test cases in parallel.
    
    Features:
    - Configurable parallelism
    - Priority-based ordering
    - Progress callbacks
    - Error isolation
    """
    
    def __init__(self):
        self._metrics = get_metrics()
        self._active_batches: Dict[str, BatchProgress] = {}
    
    async def process(
        self,
        request: BatchRequest,
        progress_callback: Optional[Callable[[BatchProgress], None]] = None,
    ) -> BatchResult:
        """
        Process a batch of test cases.
        
        Args:
            request: Batch request with test cases
            progress_callback: Optional callback for progress updates
            
        Returns:
            BatchResult with all results
        """
        batch_id = uuid.uuid4().hex[:12]
        started_at = datetime.now(timezone.utc)
        start_time = time.perf_counter()
        
        logger.info(
            "Batch started | batch_id=%s | items=%d | parallel=%d",
            batch_id, len(request.items), request.parallel,
        )
        
        # Sort by priority (higher first)
        sorted_items = sorted(
            request.items,
            key=lambda x: x.priority,
            reverse=True,
        )
        
        # Initialize progress
        progress = BatchProgress(
            batch_id=batch_id,
            status=BatchStatus.PROCESSING,
            total_items=len(sorted_items),
            completed_items=0,
            progress_percent=0.0,
        )
        self._active_batches[batch_id] = progress
        
        # Process with semaphore for parallelism
        semaphore = asyncio.Semaphore(request.parallel)
        results: List[BatchItemResult] = []
        
        async def process_item(item) -> BatchItemResult:
            async with semaphore:
                item_start = time.perf_counter()
                test_case = item.test_case

                # Update progress
                progress.current_item = test_case.test_case_id
                if progress_callback:
                    progress_callback(progress)

                try:
                    # Delegate entirely to GenerationService — single pipeline
                    # implementation shared with /generate and /stream.
                    svc = GenerationService()
                    result = await svc.generate(test_case)

                    duration_ms = (time.perf_counter() - item_start) * 1000

                    logger.info(
                        "Batch item success | batch_id=%s | test_case=%s | duration_ms=%.2f",
                        batch_id, test_case.test_case_id, duration_ms,
                    )

                    return BatchItemResult(
                        test_case_id=test_case.test_case_id,
                        status=BatchItemStatus.SUCCESS,
                        script_path=str(result.path),
                        duration_ms=duration_ms,
                        tokens_used=result.total_tokens,
                    )

                except Exception as e:
                    duration_ms = (time.perf_counter() - item_start) * 1000

                    logger.error(
                        "Batch item failed | batch_id=%s | test_case=%s | error=%s",
                        batch_id, test_case.test_case_id, str(e),
                        exc_info=True,
                    )

                    return BatchItemResult(
                        test_case_id=test_case.test_case_id,
                        status=BatchItemStatus.FAILED,
                        error=str(e),
                        duration_ms=duration_ms,
                    )
                finally:
                    progress.completed_items += 1
                    progress.progress_percent = (
                        progress.completed_items / progress.total_items * 100
                    )
                    progress.current_item = None

                    if progress_callback:
                        progress_callback(progress)
        
        # Process all items
        if request.stop_on_error:
            # Sequential with early termination
            for item in sorted_items:
                result = await process_item(item)
                results.append(result)
                
                if result.status == BatchItemStatus.FAILED:
                    # Mark remaining as skipped
                    remaining = sorted_items[len(results):]
                    for remaining_item in remaining:
                        results.append(BatchItemResult(
                            test_case_id=remaining_item.test_case.test_case_id,
                            status=BatchItemStatus.SKIPPED,
                            error="Skipped due to previous error",
                        ))
                    break
        else:
            # Parallel processing
            tasks = [process_item(item) for item in sorted_items]
            results = await asyncio.gather(*tasks)
        
        # Compute totals from results (race-condition-free — no concurrent mutation)
        total_tokens = sum(r.tokens_used for r in results if r.tokens_used)
        failed_count = sum(1 for r in results if r.status == BatchItemStatus.FAILED)
        completed_count = sum(1 for r in results if r.status == BatchItemStatus.SUCCESS)
        skipped_count = sum(1 for r in results if r.status == BatchItemStatus.SKIPPED)

        total_duration_ms = (time.perf_counter() - start_time) * 1000
        completed_at = datetime.now(timezone.utc)

        # Determine final status
        if failed_count == 0 and skipped_count == 0:
            status = BatchStatus.COMPLETED
        elif completed_count == 0:
            status = BatchStatus.FAILED
        else:
            status = BatchStatus.PARTIAL

        # Sum per-item cost estimates rather than extrapolating from one sample (BUG-12 fix)
        settings = get_settings()
        cost_estimate = 0.0
        try:
            for item in sorted_items:
                tc = item.test_case
                est = estimate_cost(
                    description=tc.description,
                    steps=tc.steps,
                    prerequisites=getattr(tc, "prerequisites", []),
                    provider=settings.LLM_PROVIDER,
                    model=settings.PRIMARY_MODEL,
                )
                cost_estimate += est.estimated_cost_usd
            cost_estimate = round(cost_estimate, 6)
        except Exception:
            logger.warning(
                "Cost estimation failed for batch=%s, defaulting to 0.0",
                batch_id,
            )
            cost_estimate = 0.0

        # Clean up completed batch from active tracking
        del self._active_batches[batch_id]

        logger.info(
            "Batch completed | batch_id=%s | status=%s | success=%d | failed=%d | skipped=%d | duration_ms=%.2f",
            batch_id, status.value, completed_count, failed_count, skipped_count, total_duration_ms,
        )

        return BatchResult(
            batch_id=batch_id,
            status=status,
            total_items=len(sorted_items),
            completed_items=completed_count,
            failed_items=failed_count,
            skipped_items=skipped_count,
            results=list(results),
            total_duration_ms=total_duration_ms,
            total_tokens_used=total_tokens,
            cost_estimate_usd=cost_estimate,
            started_at=started_at,
            completed_at=completed_at,
        )
    
    def get_progress(self, batch_id: str) -> Optional[BatchProgress]:
        """Get progress for an active batch."""
        return self._active_batches.get(batch_id)
    
    def list_active_batches(self) -> List[BatchProgress]:
        """List all active batches."""
        return list(self._active_batches.values())

