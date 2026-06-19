from typing import Any, Dict

from fastapi import UploadFile

from app.core.errors import internal_error, not_found_error, validation_error
from app.core.logging import get_logger
from app.core.validation import (
    validate_content_type,
    validate_file_size,
    validate_filename,
    validate_html_content,
    validate_report_name,
)
from app.db.mongo import (
    delete_all_reports,
    delete_report_by_id,
    get_report_by_id,
    get_report_content,
    insert_report,
    list_reports,
)

logger = get_logger(__name__)


async def store_report(name: str, file: UploadFile) -> Dict[str, Any]:
    try:
        cleaned_name = validate_report_name(name)
        original_filename = validate_filename(file.filename)
        content_type = validate_content_type(file.content_type)

        content = await file.read()

        validate_file_size(content)

        try:
            html_content = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise validation_error("Invalid UTF-8 encoding") from exc

        validate_html_content(html_content)

        report = await insert_report(
            name=cleaned_name,
            filename=original_filename,
            html_bytes=html_content.encode("utf-8"),
            content_type=content_type,
        )
        logger.info(
            "Report uploaded",
            extra={
                "report_id": report["report_id"],
                "report_name": cleaned_name,
                "size": report["size"],
            },
        )
        return report
    finally:
        await file.close()


async def fetch_report(report_id: str) -> Dict[str, Any]:
    report = await get_report_by_id(report_id)
    if not report:
        raise not_found_error(message=f"Report {report_id} not found")

    try:
        content_bytes = await get_report_content(report_id)
        html_content = content_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise internal_error("Corrupted report data") from exc

    return {
        "id": report["_id"],
        "name": report["name"],
        "html_content": html_content,
        "content_type": report["content_type"],
        "created_at": report["created_at"],
        "updated_at": report["updated_at"],
        "size": report["size"],
        "filename": report.get("filename"),
    }


async def list_report_metadata(*, skip: int = 0, limit: int = 50) -> list[Dict[str, Any]]:
    return await list_reports(skip=skip, limit=limit)


async def delete_report(report_id: str) -> None:
    deleted = await delete_report_by_id(report_id)
    if not deleted:
        raise not_found_error(message=f"Report {report_id} not found")


async def delete_reports(confirm: bool) -> int:
    if not confirm:
        raise validation_error("Confirmation required. Pass ?confirm=true to delete all reports.")
    return await delete_all_reports()
