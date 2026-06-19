import io
import time
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.core.metrics import Metrics
from app.core.security import verify_api_key
from app.core.utils import safe_decode
from app.db.mongo import store_raw_script
from app.services.extraction_service import extract_methods_from_source
from app.services.validator import ValidationError

settings = get_settings()
router = APIRouter()


@router.post(
    "/",
    summary="Extract methods from a Playwright Python script and return them as CSV",
)
async def extract_methods(
    request: Request,
    background_tasks: BackgroundTasks,
    file: Optional[UploadFile] = File(None),
    script: Optional[str] = Form(None),
    include_method_name_pattern: Optional[str] = Form(None),
    token: dict = Depends(verify_api_key),
):
    start = time.perf_counter()

    if not file and (not script or script.strip() == ""):
        raise HTTPException(
            status_code=400,
            detail="Provide either a file or a 'script' text field.",
        )

    if file:
        filename = file.filename or "uploaded_playwright_script.py"
        raw_bytes = await file.read()
        if settings.MAX_SCRIPT_SIZE_BYTES > 0 and len(raw_bytes) > settings.MAX_SCRIPT_SIZE_BYTES:
            raise HTTPException(
                status_code=400,
                detail="Uploaded script exceeds the maximum allowed size.",
            )
        source_text = safe_decode(raw_bytes)
        source_type = "file_upload"
    else:
        filename = "pasted_playwright_script.py"
        source_text = script or ""
        source_type = "form_field"

    request.state.audit_context = {
        "file_name": filename,
        "source_type": source_type,
        "storage_requested": settings.STORE_RAW_SCRIPTS,
    }

    try:
        result = extract_methods_from_source(
            source_text,
            max_chars_per_chunk=settings.MAX_CHARS_PER_CHUNK,
            ignore_method_names=settings.IGNORE_METHOD_NAMES,
            include_method_name_pattern=include_method_name_pattern or settings.INCLUDE_METHOD_NAME_PATTERN or None,
        )
    except SyntaxError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid Python syntax: {exc.msg}") from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    Metrics.record_extraction()
    request.state.audit_context.update(
        {
            "method_count": len(result.methods),
            "chunk_count": len(result.chunks),
            "duration_ms": round((time.perf_counter() - start) * 1000, 2),
        }
    )

    if settings.STORE_RAW_SCRIPTS:
        background_tasks.add_task(
            store_raw_script,
            filename,
            source_text,
            {"source_type": source_type},
        )

    download_name = f"methods_{int(time.time())}.csv"
    return StreamingResponse(
        io.BytesIO(result.csv_bytes),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
    )
