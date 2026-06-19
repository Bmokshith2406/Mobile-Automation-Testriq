# app/routes/generate_matrix.py
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from typing import Optional
import logging
import asyncio
import uuid

from app.models.test_case import TestCase
from app.services.matrix_generation_service import MatrixGenerationService
from app.services.webhook_notifier import WebhookNotifier
from app.core.exceptions import ExtractionError, CodeGenerationError
from app.core.metrics import get_metrics

router = APIRouter()
logger = logging.getLogger("api.generate_matrix")

_matrix_generation_service = MatrixGenerationService()
_webhook_notifier = WebhookNotifier()
_metrics = get_metrics()


@router.post(
    "/",
    summary="Generate multi-device Playwright ZIP",
    response_description="Generated Playwright ZIP archive",
    responses={
        200: {"description": "ZIP archive generated successfully"},
        422: {"description": "CIR validation failed"},
        429: {"description": "Rate limit exceeded"},
        500: {"description": "Internal server error"},
    },
)
async def generate_matrix(
    test_case: TestCase,
    webhook_url: Optional[str] = None,
) -> FileResponse:
    """
    Generate multiple Playwright test scripts tailored for different devices and return them as a ZIP file.
    """
    fallback_request_id = uuid.uuid4().hex[:8]

    try:
        result = await _matrix_generation_service.generate(test_case)

        # Send webhook notification (fire and forget)
        if webhook_url:
            task = asyncio.create_task(
                _webhook_notifier.notify(
                    webhook_url,
                    {
                        "request_id": result.request_id,
                        "status": "success",
                        "test_case_id": test_case.test_case_id,
                        "duration_ms": round(result.duration_ms, 2),
                        "tokens_used": result.total_tokens,
                    },
                )
            )
            _webhook_notifier.add_task(task)
        
        response = FileResponse(
            path=result.path,
            filename=result.path.name,
            media_type="application/zip",
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
        
        if webhook_url:
            task = asyncio.create_task(
                _webhook_notifier.notify(
                    webhook_url,
                    {
                        "request_id": fallback_request_id,
                        "status": "failed",
                        "test_case_id": test_case.test_case_id,
                        "error": str(e),
                    },
                )
            )
            _webhook_notifier.add_task(task)
        
        raise HTTPException(
            status_code=500,
            detail="Matrix script generation failed due to an internal error.",
        )
