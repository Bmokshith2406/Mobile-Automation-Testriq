# app/routes/stream.py
"""
Streaming Generation Endpoint

Production-grade SSE implementation:
- Safe cancellation handling
- Timeout protection
- Structured logging
- Generator isolation
- Concurrency protection
- Proper SSE format
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from typing import AsyncIterator, Optional
import json
import logging
import time
import uuid
import asyncio

from app.models.test_case import TestCase
from app.services.cir_builder import CIRBuilder
from app.services.validator import CIRValidator, CIRValidationError
from app.services.generators.generator_factory import get_generator
from app.services.assembler import ScriptAssembler
from app.core.token_tracker import (
    reset_tokens,
    get_input_tokens,
    get_output_tokens,
)
from app.core.config import get_settings

router = APIRouter()
logger = logging.getLogger("api.stream")

# Services (module-level singletons; stateless)
_cir_builder = CIRBuilder()
_validator = CIRValidator()
_assembler = ScriptAssembler()

# Concurrency semaphore — lazily created inside the running event loop
# to avoid the Python 3.10+ deprecation of creating asyncio primitives
# at import time (before the event loop is started).
_stream_semaphore: Optional[asyncio.Semaphore] = None


def _get_stream_semaphore() -> asyncio.Semaphore:
    global _stream_semaphore
    if _stream_semaphore is None:
        limit = get_settings().STREAM_MAX_CONCURRENT
        _stream_semaphore = asyncio.Semaphore(limit)
    return _stream_semaphore


# ==========================================================
# SSE EVENT GENERATOR
# ==========================================================

async def generate_events(
    test_case: TestCase,
    request_id: str,
) -> AsyncIterator[str]:

    def sse(event_name: str, payload: dict) -> str:
        return (
            f"event: {event_name}\n"
            f"data: {json.dumps(payload)}\n\n"
        )

    start_time = time.time()

    try:
        reset_tokens()

        yield sse("init", {
            "request_id": request_id,
            "test_case_id": test_case.test_case_id,
            "timestamp": start_time,
        })

        # --------------------------------------------------
        # CIR BUILD
        # --------------------------------------------------
        yield sse("cir_build", {"status": "started"})

        t0 = time.perf_counter()
        cir_test_case, context_map = await asyncio.wait_for(
            _cir_builder.build(test_case),
            timeout=60,
        )

        yield sse("cir_build", {
            "status": "completed",
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
            "setup_blocks": len(cir_test_case.setup),
            "step_blocks": len(cir_test_case.steps),
        })

        # --------------------------------------------------
        # VALIDATION
        # --------------------------------------------------
        yield sse("validation", {"status": "started"})
        t0 = time.perf_counter()

        try:
            _validator.validate_blocks(
                cir_test_case.setup + cir_test_case.steps + cir_test_case.teardown
            )
        except CIRValidationError as e:
            yield sse("validation", {"status": "failed", "error": str(e)})
            yield sse("generation", {"status": "failed"})
            return

        yield sse("validation", {
            "status": "completed",
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
        })

        # --------------------------------------------------
        # CODE GENERATION
        # --------------------------------------------------
        yield sse("code_generation", {"status": "started"})
        t0 = time.perf_counter()

        from app.core.context import active_framework_ctx
        settings = get_settings()
        framework = test_case.target_framework or settings.AUTOMATION_FRAMEWORK
        active_framework_ctx.set(framework)

        # Create generator per request (avoid shared state corruption)
        generator = get_generator(framework)

        generated_code = await asyncio.wait_for(
            generator.generate(
                cir_test_case=cir_test_case,
                context_map=context_map,
            ),
            timeout=180,
        )

        if not generated_code or not generated_code.strip():
            yield sse("code_generation", {
                "status": "failed",
                "error": "Empty script generated",
            })
            yield sse("generation", {"status": "failed"})
            return

        yield sse("code_generation", {
            "status": "completed",
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
            "code_chars": len(generated_code),
        })

        # --------------------------------------------------
        # ASSEMBLY
        # --------------------------------------------------
        yield sse("assembly", {"status": "started"})
        t0 = time.perf_counter()

        script_path = await _assembler.assemble_async(
            test_case_id=test_case.test_case_id,
            code=generated_code,
            framework=framework,
            request_id=request_id,
        )

        yield sse("assembly", {
            "status": "completed",
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
            "script_filename": script_path.name,
        })

        # --------------------------------------------------
        # FINAL SUCCESS
        # --------------------------------------------------
        yield sse("generation", {
            "status": "completed",
            "script_filename": script_path.name,
            "input_tokens": get_input_tokens(),
            "output_tokens": get_output_tokens(),
            "total_duration_ms": round(
                (time.time() - start_time) * 1000, 2
            ),
        })

    except asyncio.CancelledError:
        logger.info("Stream cancelled | id=%s", request_id)
        yield sse("generation", {"status": "cancelled"})
        raise

    except asyncio.TimeoutError:
        logger.error("Stream timeout | id=%s", request_id)
        yield sse("generation", {
            "status": "failed",
            "error": "Generation timeout",
        })

    except Exception as e:
        logger.exception("Stream generation failed | id=%s", request_id)
        yield sse("generation", {
            "status": "failed",
            "error": str(e),
        })


# ==========================================================
# ROUTE
# ==========================================================

@router.post("/generate")
async def stream_generate_script(
    test_case: TestCase,
    request: Request,
) -> StreamingResponse:

    request_id = uuid.uuid4().hex[:8]

    logger.info(
        "stream_request",
        extra={
            "request_id": request_id,
            "test_case_id": test_case.test_case_id,
        },
    )

    sem = _get_stream_semaphore()
    try:
        await asyncio.wait_for(sem.acquire(), timeout=0.001)
    except asyncio.TimeoutError:
        logger.warning("Stream concurrency limit reached")
        raise HTTPException(
            status_code=429,
            detail="Too many concurrent streaming requests",
        )

    async def wrapped_generator():
        try:
            async for chunk in generate_events(test_case, request_id):
                yield chunk
        finally:
            sem.release()

    return StreamingResponse(
        wrapped_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Request-ID": request_id,
        },
    )

