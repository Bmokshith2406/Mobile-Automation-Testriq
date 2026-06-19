import io
import time

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.core.metrics import Metrics
from app.core.security import verify_api_key
from app.services.extraction_service import extract_methods_from_project_zip
from app.services.validator import ValidationError


settings = get_settings()
router = APIRouter()


@router.post(
    "/extract-project",
    summary="Extract methods from a Playwright Python project (ZIP upload)",
)
async def extract_project(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    include_method_name_pattern: Optional[str] = Form(None),
    token: dict = Depends(verify_api_key),
):
    del background_tasks

    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(
            status_code=400,
            detail="Only ZIP files are supported for project extraction.",
        )

    start = time.perf_counter()
    zip_bytes = await file.read()

    request.state.audit_context = {
        "file_name": file.filename,
        "source_type": "zip_upload",
        "storage_requested": False,
    }

    try:
        result = extract_methods_from_project_zip(
            zip_bytes,
            settings=settings,
            ignore_method_names=settings.IGNORE_METHOD_NAMES,
            include_method_name_pattern=include_method_name_pattern or settings.INCLUDE_METHOD_NAME_PATTERN or None,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    Metrics.record_extraction()
    request.state.audit_context.update(
        {
            "method_count": len(result.methods),
            "chunk_count": len(result.chunks),
            "python_file_count": result.python_file_count,
            "total_file_count": result.total_file_count,
            "skipped_file_count": result.skipped_file_count,
            "duration_ms": round((time.perf_counter() - start) * 1000, 2),
        }
    )

    download_name = f"project_methods_{int(time.time())}.csv"
    return StreamingResponse(
        io.BytesIO(result.csv_bytes),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
    )
