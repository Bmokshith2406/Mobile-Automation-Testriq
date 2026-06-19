from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import Response

from app.core.errors import ProductionError, internal_error, validation_error
from app.core.logging import get_logger
from app.core.metrics import Metrics
from app.core.security import verify_admin_api_key, verify_api_key
from app.models.schemas import (
    ReportDeleteAllResponse,
    ReportDeleteResponse,
    ReportListResponse,
    ReportUploadResponse,
)
from app.services.report_service import delete_report, delete_reports, fetch_report, list_report_metadata, store_report

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/reports",
    tags=["reports"],
    dependencies=[Depends(verify_api_key)],
)

admin_router = APIRouter(
    prefix="/api/reports",
    tags=["reports-admin"],
    dependencies=[Depends(verify_admin_api_key)],
)


@router.post(
    "/upload",
    response_model=ReportUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_report(
    name: str = Form(...),
    file: UploadFile = File(...),
):
    try:
        report = await store_report(name=name, file=file)
        Metrics.record_report_upload()
        return {
            "status": "success",
            "message": "Report uploaded successfully",
            "report_id": report["report_id"],
            "name": report["name"],
            "created_at": report["created_at"],
        }
    except ProductionError:
        raise
    except Exception as exc:
        logger.exception("Upload failed", extra={"error": str(exc)})
        raise internal_error("Failed to upload report") from exc


@router.get("/download/{report_id}")
async def download_report(report_id: str):
    try:
        report = await fetch_report(report_id)
        Metrics.record_report_download()
        return Response(
            content=report["html_content"],
            media_type="text/html; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{report["name"]}.html"',
                "Content-Security-Policy": "default-src 'none'; img-src data: https: http:; style-src 'unsafe-inline'; sandbox",
                "X-Content-Type-Options": "nosniff",
                "X-Report-ID": report["id"],
            },
        )
    except ProductionError:
        raise
    except Exception as exc:
        logger.exception(
            "Download failed",
            extra={"report_id": report_id, "error": str(exc)},
        )
        raise internal_error("Internal server error while downloading report") from exc


@admin_router.get("", response_model=ReportListResponse)
async def list_reports(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
):
    try:
        reports = await list_report_metadata(skip=skip, limit=limit)
        return {
            "success": True,
            "count": len(reports),
            "skip": skip,
            "limit": limit,
            "reports": reports,
        }
    except ProductionError:
        raise
    except Exception as exc:
        logger.exception("Report list failed", extra={"error": str(exc)})
        raise internal_error("Failed to list reports") from exc


@admin_router.delete("/{report_id}", response_model=ReportDeleteResponse)
async def delete_single_report(report_id: str):
    try:
        await delete_report(report_id)
        return {
            "success": True,
            "report_id": report_id,
            "message": "Report deleted successfully",
        }
    except ProductionError:
        raise
    except Exception as exc:
        logger.exception("Report delete failed", extra={"report_id": report_id, "error": str(exc)})
        raise internal_error("Failed to delete report") from exc


@admin_router.post("/delete-all", response_model=ReportDeleteAllResponse)
async def delete_all_reports(confirm: bool = Query(False, description="Pass true to confirm deletion")):
    if not confirm:
        raise validation_error("Confirmation required. Pass ?confirm=true to delete all reports.")

    try:
        deleted_count = await delete_reports(confirm=confirm)
        return {
            "success": True,
            "deleted_reports": deleted_count,
            "message": "All reports deleted successfully",
        }
    except ProductionError:
        raise
    except Exception as exc:
        logger.exception("Delete all reports failed", extra={"error": str(exc)})
        raise internal_error("Failed to delete reports") from exc
