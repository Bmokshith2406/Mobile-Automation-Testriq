"""
Repair API Route - Production Grade

Features:
- Bounded concurrency
- Metrics integration
- Tracing support
- Database persistence
- Enhanced error handling
"""

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import PlainTextResponse, JSONResponse
import logging
import time
import uuid
import json
import asyncio
from typing import Optional

from app.services.repair_service import RepairService
from app.services.repair_pipeline import repair_pipeline_safe
from app.models.step_repair import StepRepairRequest
from app.core.exceptions import StepNotRepairableError
from app.core.config import get_settings
from app.core.metrics import get_metrics
from app.core.tracing import trace, SpanKind
from app.core.database import get_repository, RepairRecord
from app.core.security import require_api_key

# Import context utilities
from app.core.utils import set_correlation_id


router = APIRouter()
logger = logging.getLogger("api.repair")
settings = get_settings()
# Bounded concurrency control
MAX_CONCURRENT_REPAIRS = 5
repair_semaphore = asyncio.Semaphore(MAX_CONCURRENT_REPAIRS)

_REPAIR_SERVICE = RepairService(
    semaphore=repair_semaphore,
    pipeline_fn=repair_pipeline_safe
)
# ==================================================
# LIMITS & GUARDS
# ==================================================

MAX_PAYLOAD_BYTES = settings.MAX_REQUEST_SIZE_BYTES
SCHEMA_VERSION = "3.0"

# ==================================================
# API ROUTE
# ==================================================

@router.post(
    "",
    summary="Repair a failed test automation step",
    description="Analyzes a failed test step (Playwright, Selenium, Appium, Cypress) and generates repaired code using LLM-powered analysis.",
    response_description="Repaired step code",
    tags=["repair"],
    responses={
        200: {"description": "Successfully repaired step"},
        400: {"description": "Invalid request payload"},
        409: {"description": "Step is not repairable"},
        413: {"description": "Payload too large"},
        429: {"description": "Rate limit exceeded"},
        504: {"description": "Repair operation timed out"},
    },
)
@trace(name="repair.step", kind=SpanKind.SERVER)
async def repair_step(
    request: Request,
    payload: str = Form(..., description="JSON payload with step repair request"),
    error_image: UploadFile | None = File(None, description="Screenshot at failure time (PNG, JPEG, or WebP)"),
):
    """
    Repair a failed test automation step.
    
    This endpoint accepts a JSON payload describing the failed step and optionally
    a screenshot captured at failure time. It uses LLM analysis to generate repaired code.
    """
    request_id = getattr(request.state, "request_id", None) or uuid.uuid4().hex[:12]
    set_correlation_id(request_id)
    start_ts = time.perf_counter()
    metrics = get_metrics()

    # ---------------- Payload size guard ----------------
    if len(payload.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        metrics.repair_requests_total.inc(outcome="rejected", action_type="unknown")
        raise HTTPException(status_code=413, detail="Payload too large")

    # ---------------- Parse request ----------------
    try:
        data = json.loads(payload)
        request = StepRepairRequest(**data)
    except json.JSONDecodeError as e:
        metrics.repair_requests_total.inc(outcome="invalid_input", action_type="unknown")
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {str(e)}")
    except Exception as e:
        metrics.repair_requests_total.inc(outcome="invalid_input", action_type="unknown")
        raise HTTPException(status_code=400, detail=f"Invalid payload: {str(e)}")

    logger.info(
        "REPAIR_START | request_id=%s | step_id=%s | error_type=%s",
        request_id,
        request.step_id,
        request.error_classification.type,
    )

    # ---------------- PNG validation ----------------
    error_image_bytes: Optional[bytes] = None

    if error_image:
        image_bytes = await error_image.read()

        if len(image_bytes) > settings.MAX_SCREENSHOT_SIZE_BYTES:
            metrics.repair_requests_total.inc(outcome="invalid_input", action_type="unknown")
            raise HTTPException(status_code=400, detail="Image too large")

        detected_mime_type = _detect_image_mime_type(image_bytes)
        if not detected_mime_type:
            metrics.repair_requests_total.inc(outcome="invalid_input", action_type="unknown")
            raise HTTPException(status_code=400, detail="Invalid image file")

        if detected_mime_type not in settings.ALLOWED_SCREENSHOT_MIME_TYPES:
            metrics.repair_requests_total.inc(outcome="invalid_input", action_type="unknown")
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported image type. Allowed: {settings.ALLOWED_SCREENSHOT_MIME_TYPES}"
            )

        error_image_bytes = image_bytes

    # ---------------- Dry run mode ----------------
    if settings.DRY_RUN_MODE:
        logger.info("DRY_RUN | request_id=%s | step_id=%s", request_id, request.step_id)
        return _success_response(
            request_id=request_id,
            step_id=request.step_id,
            code="# Dry run mode - no actual repair performed\n" + request.original_code,
            start_ts=start_ts,
            action_type="dry_run",
            framework=request.framework,
        )

    # ---------------- Execute Repair ----------------
    try:
        code, action_type = await _REPAIR_SERVICE.repair_step(
            request=request,
            error_image_bytes=error_image_bytes,
            request_id=request_id,
        )

        duration_ms = int((time.perf_counter() - start_ts) * 1000)
        metrics.repair_requests_total.inc(
            outcome="success",
            action_type=action_type,
        )

        await _save_repair_record(
            request=request,
            repaired_code=code,
            outcome="success",
            duration_ms=duration_ms,
            request_id=request_id,
        )

        return _success_response(
            request_id=request_id,
            step_id=request.step_id,
            code=code,
            start_ts=start_ts,
            action_type=action_type,
            framework=request.framework,
        )

    except asyncio.TimeoutError:
        duration_ms = int((time.perf_counter() - start_ts) * 1000)

        metrics.repair_requests_total.inc(
            outcome="timeout",
            action_type="unknown",
        )

        await _save_repair_record(
            request=request,
            repaired_code=None,
            outcome="timeout",
            duration_ms=duration_ms,
            request_id=request_id,
        )

        return _error_response(
            status_code=504,
            outcome="TIMEOUT",
            retryable=True,
            message="Repair operation timed out",
            request_id=request_id,
            step_id=request.step_id,
        )

    except StepNotRepairableError as exc:
        duration_ms = int((time.perf_counter() - start_ts) * 1000)

        metrics.repair_requests_total.inc(
            outcome="not_repairable",
            action_type="unknown",
        )

        await _save_repair_record(
            request=request,
            repaired_code=None,
            outcome="not_repairable",
            duration_ms=duration_ms,
            request_id=request_id,
            error_message=str(exc),
        )

        return _error_response(
            status_code=409,
            outcome="NOT_REPAIRABLE",
            retryable=False,
            message=str(exc),
            details=getattr(exc, "details", None),
            request_id=request_id,
            step_id=request.step_id,
        )

    except Exception:
        duration_ms = int((time.perf_counter() - start_ts) * 1000)

        metrics.repair_requests_total.inc(
            outcome="error",
            action_type="unknown",
        )

        await _save_repair_record(
            request=request,
            repaired_code=None,
            outcome="model_error",
            duration_ms=duration_ms,
            request_id=request_id,
        )

        logger.exception(
            "REPAIR_FAILURE | request_id=%s | step_id=%s",
            request_id,
            request.step_id,
        )

        return _error_response(
            status_code=500,
            outcome="MODEL_ERROR",
            retryable=True,
            message="Internal repair error",
            request_id=request_id,
            step_id=request.step_id,
        )

# ==================================================
# DATABASE PERSISTENCE
# ==================================================

async def _save_repair_record(
    *,
    request: StepRepairRequest,
    repaired_code: Optional[str],
    outcome: str,
    duration_ms: int,
    request_id: str,
    error_message: Optional[str] = None,
):
    """Save repair record to database."""
    try:
        repo = await get_repository()
        
        record = RepairRecord(
            step_id=request.step_id,
            original_code=request.original_code,
            repaired_code=repaired_code,
            intent=request.step_intent,
            error_type=request.error_classification.type,
            error_message=error_message or request.error_details.message,
            outcome=outcome,
            duration_ms=duration_ms,
            model_name=settings.LLM_MODEL_NAME,
            request_id=request_id,
        )
        
        await repo.save_repair(record)
        logger.debug("Saved repair record: %s", record.id)
    except Exception as e:
        # Don't fail the request if database save fails
        logger.warning("Failed to save repair record: %s", e)


# ==================================================
# RESPONSES
# ==================================================

def _success_response(
    *,
    request_id: str,
    step_id: str,
    code: str,
    start_ts: float,
    action_type: str,
    framework: str = "playwright",
):
    duration_ms = round((time.perf_counter() - start_ts) * 1000, 2)

    logger.info(
        "REPAIR_SUCCESS | request_id=%s | step_id=%s | action_type=%s | duration_ms=%s",
        request_id,
        step_id,
        action_type,
        duration_ms,
    )

    ext = ".js" if (framework or "").strip().lower() == "cypress" else ".py"
    media_type = "text/javascript; charset=utf-8" if ext == ".js" else "text/x-python; charset=utf-8"

    return PlainTextResponse(
        content=code.strip() + "\n",
        media_type=media_type,
        headers={
            "X-Request-ID": request_id,
            "X-Step-ID": step_id,
            "X-Repair-Outcome": "SUCCESS",
            "X-Action-Type": action_type,
            "X-Duration-Ms": str(duration_ms),
            "X-Schema-Version": SCHEMA_VERSION,
            "Content-Disposition": f'attachment; filename="{step_id}_repaired{ext}"',
        },
    )


def _error_response(
    *,
    status_code: int,
    outcome: str,
    retryable: bool,
    message: str,
    request_id: str,
    step_id: str,
    details: dict | None = None,
):
    return JSONResponse(
        status_code=status_code,
        content={
            "type": outcome,
            "outcome": outcome,
            "retryable": retryable,
            "message": message,
            "details": details,
            "request_id": request_id,
            "step_id": step_id,
            "schema_version": SCHEMA_VERSION,
        },
        headers={
            "X-Request-ID": request_id,
            "X-Step-ID": step_id,
            "X-Repair-Outcome": outcome,
            "X-Retryable": str(retryable).lower(),
            "X-Schema-Version": SCHEMA_VERSION,
        },
    )


def _detect_image_mime_type(image_bytes: bytes) -> Optional[str]:
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"

    if image_bytes[:3] == b"\xff\xd8\xff":
        return "image/jpeg"

    if len(image_bytes) >= 12 and image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"

    return None
