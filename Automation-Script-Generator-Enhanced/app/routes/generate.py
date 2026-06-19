# app/routes/generate.py
"""
Script Generation Endpoint

Main endpoint for generating automation test scripts.
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Optional
import logging
import asyncio
import uuid
from pathlib import Path

from app.models.test_case import TestCase
from app.services.generation_service import GenerationService
from app.services.assembler import ScriptAssembler
from app.services.webhook_notifier import get_webhook_notifier
from app.core.exceptions import ExtractionError, CodeGenerationError
from app.core.config import get_settings as _get_settings
from app.core.metrics import get_metrics

router = APIRouter()
logger = logging.getLogger("api.generate")

_generation_service = GenerationService()
_metrics = get_metrics()

# Resolve the safe output directory once at module load time.
# All served files are validated to live inside this directory.
_OUTPUT_DIR: Path = ScriptAssembler().output_dir.resolve()


# ---------------------------------------------------------------------------
# Request schema — webhook_url moved from query param into the body so it
# never appears in server access logs, CDN logs, or browser history.
# ---------------------------------------------------------------------------

class GenerateRequest(BaseModel):
    """Request body for the script generation endpoint."""

    test_case: TestCase = Field(..., description="Test case specification")
    webhook_url: Optional[str] = Field(
        default=None,
        description=(
            "Optional URL to POST a completion notification to. "
            "Must be a public https:// URL. Private/loopback IPs are blocked."
        ),
    )

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post(
    "/",
    summary="Generate Automation Test Script",
    response_description="Generated test script file",
    responses={
        200: {"description": "Script generated successfully"},
        422: {"description": "CIR validation failed"},
        429: {"description": "Rate limit exceeded"},
        500: {"description": "Internal server error"},
    },
)
async def generate_script(body: GenerateRequest, request: Request) -> FileResponse:
    """
    Generate an automation test script from a test case specification.

    The generation pipeline:
    1. Build CIR (Canonical Intermediate Representation) from test case
    2. Validate CIR structure
    3. Generate the framework-specific code
    4. Assemble into executable script file

    Returns:
        FileResponse with the generated Python script
    """
    test_case = body.test_case
    webhook_url = body.webhook_url
    http_request_id = (
        request.headers.get("x-request-id")
        or request.headers.get("x-correlation-id")
        or uuid.uuid4().hex[:8]
    )
    fallback_request_id = http_request_id

    try:
        try:
            result = await asyncio.wait_for(
                _generation_service.generate(test_case, http_request_id=http_request_id),
                timeout=_get_settings().GENERATION_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="Script generation timed out")

        # --- Path traversal guard ----------------------------------------
        # Ensure the file returned by the generation service lives inside the
        # expected output directory. Defends against any edge case where
        # sanitize_test_case_id or file naming produces an unexpected path.
        resolved_path = result.path.resolve()
        if not resolved_path.is_relative_to(_OUTPUT_DIR):
            logger.error(
                "Path traversal detected | resolved=%s | expected_dir=%s",
                resolved_path,
                _OUTPUT_DIR,
            )
            raise HTTPException(status_code=500, detail="Internal path error")
        # ------------------------------------------------------------------

        # Send webhook notification (fire and forget)
        if webhook_url:
            from datetime import datetime, timezone as _tz
            notifier = get_webhook_notifier()
            task = asyncio.create_task(
                notifier.notify(
                    webhook_url,
                    {
                        "event": "script.generated",
                        "schema_version": "1.0",
                        "timestamp": datetime.now(_tz.utc).isoformat(),
                        "request_id": result.request_id,
                        "status": "success",
                        "test_case_id": test_case.test_case_id,
                        "duration_ms": round(result.duration_ms, 2),
                        "tokens_used": result.total_tokens,
                    },
                )
            )
            notifier.add_task(task)

        response = FileResponse(
            path=resolved_path,
            filename=resolved_path.name,
            media_type="text/x-python; charset=utf-8",
        )

        response.headers["X-Request-ID"] = result.request_id
        response.headers["X-Input-Tokens"] = str(result.input_tokens)
        response.headers["X-Output-Tokens"] = str(result.output_tokens)
        response.headers["X-Total-Tokens"] = str(result.total_tokens)
        response.headers["X-Duration-Ms"] = str(round(result.duration_ms, 2))

        return response

    except (HTTPException, ExtractionError, CodeGenerationError):
        raise

    except Exception as e:
        logger.error(
            "Request failed | id=%s | test_case_id=%s | error=%s",
            fallback_request_id,
            test_case.test_case_id,
            str(e),
            exc_info=True,
        )
        _metrics.record_error(f"unhandled_{type(e).__name__}")

        # Send failure webhook
        if webhook_url:
            from datetime import datetime, timezone as _tz
            notifier = get_webhook_notifier()
            task = asyncio.create_task(
                notifier.notify(
                    webhook_url,
                    {
                        "event": "script.failed",
                        "schema_version": "1.0",
                        "timestamp": datetime.now(_tz.utc).isoformat(),
                        "request_id": fallback_request_id,
                        "status": "failed",
                        "test_case_id": test_case.test_case_id,
                        "error": str(e),
                    },
                )
            )
            notifier.add_task(task)

        raise HTTPException(
            status_code=500,
            detail="Script generation failed due to an internal error.",
        )
