from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status

from app.core.analytics import log_api_call
from app.core.security import verify_api_key
from app.services.ingestion_jobs import ingestion_job_manager
from app.services.upload_pipeline import process_upload_bytes, validate_upload_filename

router = APIRouter()


@router.post("/upload", status_code=status.HTTP_200_OK)
async def upload_and_process_file(
    response: Response,
    file: UploadFile = File(...),
    background: bool = Query(
        False,
        description="When true, queue the upload for background processing and return a job id.",
    ),
    current_user: dict = Depends(verify_api_key),
):
    validate_upload_filename(file.filename or "")

    try:
        contents = await file.read()
    except Exception as err:
        raise HTTPException(status_code=400, detail=f"Failed to read uploaded file: {err}")

    if background:
        try:
            job = await ingestion_job_manager.submit_job(
                filename=file.filename or "upload",
                contents=contents,
                requested_by=current_user,
            )
        except RuntimeError as err:
            raise HTTPException(status_code=503, detail=str(err))

        try:
            await log_api_call(
                endpoint="/api/upload",
                method="POST",
                user=current_user,
                payload={"filename": file.filename, "background": True},
                extra={"job_id": job["job_id"], "status": "queued"},
            )
        except Exception:
            pass

        if response is not None:
            response.status_code = status.HTTP_202_ACCEPTED

        return {
            "success": True,
            "mode": "background",
            **job,
            "status_endpoint": f"/api/upload/jobs/{job['job_id']}",
        }

    result = await process_upload_bytes(
        filename=file.filename or "upload",
        contents=contents,
        current_user=current_user,
        audit_endpoint="/api/upload",
    )
    return {
        "success": True,
        "mode": "sync",
        **result,
    }


@router.get("/upload/jobs/{job_id}", status_code=status.HTTP_200_OK)
async def get_upload_job(
    job_id: str,
    current_user: dict = Depends(verify_api_key),
):
    job = await ingestion_job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Upload job not found")

    return {
        "success": True,
        "job": job,
    }


@router.get("/upload/jobs", status_code=status.HTTP_200_OK)
async def list_upload_jobs(
    limit: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"),
    current_user: dict = Depends(verify_api_key),
):
    jobs = await ingestion_job_manager.list_jobs(limit=limit, status=status_filter)
    return {
        "success": True,
        "count": len(jobs),
        "jobs": jobs,
    }
