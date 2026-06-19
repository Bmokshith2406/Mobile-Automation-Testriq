from fastapi import APIRouter, UploadFile, File, Depends, status
from fastapi.responses import Response

from app.core.logger import get_logger
from app.core.config import get_settings
from app.core.errors import APIException, ErrorCode, ErrorCategory, ErrorSeverity
from app.services.ai import get_ai_service, AIService
from app.services.zip_service import ZipService
from app.services.report_service import ReportService
from app.workflows.report_workflow import ReportWorkflow

logger = get_logger(__name__)
settings = get_settings()

router = APIRouter(prefix=settings.API_PREFIX, tags=["Reports"])


def get_upload_file_size(file: UploadFile) -> int:
    return int(file.size) if file.size is not None else 0

def get_zip_service() -> ZipService:
    return ZipService()

def get_report_service() -> ReportService:
    return ReportService()

def get_report_workflow(
    ai_service: AIService = Depends(get_ai_service),
    zip_service: ZipService = Depends(get_zip_service),
    report_service: ReportService = Depends(get_report_service)
) -> ReportWorkflow:
    return ReportWorkflow(
        ai_service=ai_service,
        zip_service=zip_service,
        report_service=report_service
    )

@router.post(
    "/generate-report",
    status_code=status.HTTP_200_OK,
    responses={
        200: {
            "description": "Returns the generated HTML report",
            "content": {"text/html": {}}
        },
        400: {"description": "Invalid ZIP or missing artifacts"},
        413: {"description": "ZIP file too large"},
        422: {"description": "Validation Error"},
        500: {"description": "Internal processing error"},
    }
)
async def generate_report(
    file: UploadFile = File(...), 
    workflow: ReportWorkflow = Depends(get_report_workflow)
):
    """
    Generate an AI-enriched HTML report from a ZIP archive of test execution artifacts.
    """
    filename = file.filename or ""
    size_bytes = get_upload_file_size(file)

    logger.info(
        "Report generation request received",
        extra={
            "uploaded_filename": filename,
            "content_type": file.content_type,
            "size_bytes": size_bytes,
        },
    )

    if not filename.lower().endswith(".zip"):
        raise APIException(
            error_code=ErrorCode.INVALID_ZIP,
            message="File must be a ZIP archive",
            status_code=400,
            category=ErrorCategory.VALIDATION,
            severity=ErrorSeverity.WARNING,
        )

    size_mb = size_bytes / (1024 * 1024)
    if size_mb > settings.MAX_ZIP_SIZE_MB:
        raise APIException(
            error_code=ErrorCode.INVALID_ZIP,
            message=f"ZIP file exceeds maximum size of {settings.MAX_ZIP_SIZE_MB}MB",
            status_code=413,
            category=ErrorCategory.VALIDATION,
            severity=ErrorSeverity.WARNING,
        )

    # The workflow orchestrates ZipService -> AIService -> ReportService
    html_content = await workflow.execute(file)

    return Response(
        content=html_content,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=report.html"},
    )
