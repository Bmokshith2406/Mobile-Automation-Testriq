# app/routes/batch.py
"""
Batch Processing API Routes

Production-ready implementation with:
- Validation
- Defensive error handling
- Structured logging
- SSE safety
- Batch limits
- Webhook safety
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from typing import Dict, Any
import json
import asyncio
import logging

from app.models.batch import (
    BatchRequest,
    BatchResult,
    BatchProgress,
)
from app.services.batch_processor import BatchProcessor
from app.services.webhook_notifier import get_webhook_notifier
from app.core.cost_estimator import estimate_cost, get_pricing
from app.core.config import get_settings

router = APIRouter()
logger = logging.getLogger("api.batch")

_batch_processor = BatchProcessor()


# ==============================
# ROUTES
# ==============================

@router.post(
    "/",
    response_model=BatchResult,
    summary="Process batch of test cases",
    description="Generate automation scripts for multiple test cases in parallel.",
)
async def process_batch(request: BatchRequest):
    """
    Process a batch of test cases.
    """
    MAX_BATCH_SIZE = get_settings().BATCH_MAX_ITEMS

    if not request.items:
        raise HTTPException(status_code=400, detail="Batch cannot be empty")

    if len(request.items) > MAX_BATCH_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Batch size exceeds limit ({MAX_BATCH_SIZE})"
        )

    logger.info(
        "batch_request",
        extra={
            "items": len(request.items),
            "parallel": request.parallel,
        },
    )

    try:
        result = await _batch_processor.process(request)
    except ValueError as e:
        logger.warning("Batch validation error", extra={"error": str(e)})
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Batch processing failed")
        raise HTTPException(
            status_code=500,
            detail="Internal batch processing error"
        )

    # Fire-and-forget webhook with versioned event schema
    if request.webhook_url:
        from datetime import datetime, timezone as _tz
        notifier = get_webhook_notifier()
        payload = result.model_dump(mode="json")
        payload["event"] = "batch.completed"
        payload["schema_version"] = "1.0"
        payload["timestamp"] = datetime.now(_tz.utc).isoformat()

        async def safe_webhook():
            try:
                await notifier.notify(request.webhook_url, payload)
            except Exception:
                logger.exception("Webhook notification failed")

        asyncio.create_task(safe_webhook())

    return result


# ==============================
# STREAMING (SSE)
# ==============================

@router.post(
    "/stream",
    summary="Process batch with streaming progress",
    description="Process batch and stream progress updates via SSE.",
)
async def process_batch_stream(request: Request, batch: BatchRequest):
    """
    Process batch with streaming progress updates.
    """
    MAX_BATCH_SIZE = get_settings().BATCH_MAX_ITEMS

    if not batch.items:
        raise HTTPException(status_code=400, detail="Batch cannot be empty")

    if len(batch.items) > MAX_BATCH_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Batch size exceeds limit ({MAX_BATCH_SIZE})"
        )

    async def event_generator():
        progress_queue: asyncio.Queue = asyncio.Queue(maxsize=100)

        def on_progress(progress: BatchProgress):
            try:
                progress_queue.put_nowait(progress.model_copy(deep=True))
            except asyncio.QueueFull:
                logger.warning("Dropping batch progress update because SSE queue is full")
            except Exception:
                logger.exception("Failed to enqueue progress update")

        process_task = asyncio.create_task(
            _batch_processor.process(batch, progress_callback=on_progress)
        )

        try:
            while not process_task.done():

                # Detect client disconnect
                if await request.is_disconnected():
                    process_task.cancel()
                    logger.info("Client disconnected during streaming")
                    break

                try:
                    progress = await asyncio.wait_for(
                        progress_queue.get(),
                        timeout=1.0,
                    )
                    yield (
                        "event: progress\n"
                        f"data: {json.dumps(progress.model_dump())}\n\n"
                    )
                except asyncio.TimeoutError:
                    yield "event: heartbeat\ndata: {}\n\n"

            if not process_task.cancelled():
                result = await process_task
                yield (
                    "event: complete\n"
                    f"data: {json.dumps(result.model_dump(mode='json'))}\n\n"
                )

        except asyncio.CancelledError:
            logger.info("Streaming cancelled")
        except Exception as e:
            logger.exception("Batch streaming error")
            yield (
                "event: error\n"
                f"data: {json.dumps({'error': str(e)})}\n\n"
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


# ==============================
# BATCH COST ESTIMATION
# ==============================

@router.post(
    "/estimate",
    summary="Estimate batch cost",
    description="Estimate token usage and cost for a batch before processing.",
)
async def estimate_batch_cost(request: BatchRequest):
    """
    Estimate cost for a batch of test cases.
    """
    MAX_BATCH_SIZE = get_settings().BATCH_MAX_ITEMS

    if not request.items:
        raise HTTPException(status_code=400, detail="Batch cannot be empty")

    if len(request.items) > MAX_BATCH_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Batch size exceeds limit ({MAX_BATCH_SIZE})"
        )

    settings = get_settings()
    pricing = get_pricing()

    provider = settings.LLM_PROVIDER
    model = settings.PRIMARY_MODEL

    if provider not in pricing:
        raise HTTPException(status_code=400, detail="Unsupported provider")

    if model not in pricing[provider]:
        raise HTTPException(status_code=400, detail="Unsupported model")

    total_estimate: Dict[str, Any] = {
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_tokens": 0,
        "total_llm_calls": 0,
        "total_cost_usd": 0.0,
        "items": [],
        "warnings": [],
        "provider": provider,
        "model": model,
    }

    try:
        for item in request.items:
            test_case = item.test_case

            estimate = estimate_cost(
                description=test_case.description,
                steps=test_case.steps,
                prerequisites=test_case.prerequisites,
                provider=provider,
                model=model,
            )

            total_estimate["total_input_tokens"] += estimate.estimated_input_tokens
            total_estimate["total_output_tokens"] += estimate.estimated_output_tokens
            total_estimate["total_tokens"] += estimate.estimated_total_tokens
            total_estimate["total_llm_calls"] += estimate.estimated_llm_calls
            total_estimate["total_cost_usd"] += estimate.estimated_cost_usd

            total_estimate["items"].append({
                "test_case_id": test_case.test_case_id,
                **estimate.to_dict(),
            })

            total_estimate["warnings"].extend(estimate.warnings)

    except ValueError as e:
        logger.warning("Batch estimate validation error", extra={"error": str(e)})
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Batch estimate failed")
        raise HTTPException(
            status_code=500,
            detail="Internal batch estimation error"
        )

    total_estimate["total_cost_usd"] = round(total_estimate["total_cost_usd"], 6)
    total_estimate["warnings"] = list(set(total_estimate["warnings"]))

    return total_estimate

