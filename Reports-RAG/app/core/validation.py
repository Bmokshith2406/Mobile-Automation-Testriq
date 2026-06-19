import base64
import re

from app.core.config import settings
from app.core.errors import validation_error


_SAFE_REPORT_NAME = re.compile(r"^[a-zA-Z0-9_\-\. ]+$")
_HTML_EXTENSIONS = (".html", ".htm")
_ALLOWED_CONTENT_TYPES = {
    "text/html",
    "application/xhtml+xml",
    "application/octet-stream",
}


def max_file_size_bytes() -> int:
    return settings.MAX_FILE_SIZE_MB * 1024 * 1024


def validate_report_name(name: str) -> str:
    if not isinstance(name, str):
        raise validation_error("Report name must be a string")

    cleaned_name = name.strip()
    if not cleaned_name:
        raise validation_error("Report name cannot be empty")
    if len(cleaned_name) > 255:
        raise validation_error("Report name cannot exceed 255 characters")
    if not _SAFE_REPORT_NAME.fullmatch(cleaned_name):
        raise validation_error("Report name contains invalid characters")
    return cleaned_name


def validate_filename(filename: str | None) -> str:
    if not filename:
        raise validation_error("File name is required")

    cleaned_name = filename.strip()
    lower_name = cleaned_name.lower()
    if not lower_name.endswith(_HTML_EXTENSIONS):
        raise validation_error("Only .html or .htm files are allowed")
    return cleaned_name


def validate_content_type(content_type: str | None) -> str:
    if not content_type:
        return "text/html"

    base_content_type = content_type.split(";", 1)[0].strip().lower()
    if base_content_type not in _ALLOWED_CONTENT_TYPES:
        raise validation_error("Invalid file content type")
    return base_content_type


def validate_file_size(content: bytes) -> None:
    if len(content) > max_file_size_bytes():
        raise validation_error(
            f"File size exceeds {settings.MAX_FILE_SIZE_MB}MB limit"
        )


def validate_html_content(html_content: str) -> None:
    if not isinstance(html_content, str):
        raise validation_error("HTML content must be a string")

    if not html_content.strip():
        raise validation_error("HTML content cannot be empty or whitespace")

    if len(html_content.encode("utf-8")) > max_file_size_bytes():
        raise validation_error(
            f"HTML exceeds max size of {settings.MAX_FILE_SIZE_MB}MB"
        )

    normalized_html = html_content.lower()
    if "<html" not in normalized_html:
        raise validation_error("Invalid HTML: missing <html> tag")


def encode_to_base64(html_content: str) -> str:
    if not isinstance(html_content, str):
        raise validation_error("Input must be a string")

    try:
        encoded = base64.b64encode(html_content.encode("utf-8"))
        return encoded.decode("utf-8")
    except Exception as exc:
        raise validation_error(
            "Failed to encode content",
            details={"error": str(exc)},
        ) from exc


def decode_from_base64(base64_content: str) -> str:
    if not isinstance(base64_content, str):
        raise validation_error("Base64 content must be a string")

    try:
        padding = len(base64_content) % 4
        if padding:
            base64_content += "=" * (4 - padding)

        decoded_bytes = base64.b64decode(base64_content, validate=True)
        return decoded_bytes.decode("utf-8")
    except Exception as exc:
        raise validation_error(
            "Failed to decode base64 content",
            details={"error": str(exc)},
        ) from exc
