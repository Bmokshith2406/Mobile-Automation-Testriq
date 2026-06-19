"""Input validation utilities."""

import re
from typing import Optional, Any
from bson import ObjectId

from app.core.exceptions import (
    ValidationError,
    FileValidationError,
    SizeExceededError,
    InvalidObjectIdError,
)
from app.core.config import get_settings


settings = get_settings()


def validate_api_key(api_key: str) -> str:
    """Validate API key format and content."""
    if not api_key or not isinstance(api_key, str):
        raise ValidationError("API key must be a non-empty string", field="api_key")
    
    if len(api_key) < 16:
        raise ValidationError("API key is too short", field="api_key")
    
    if not api_key.isascii():
        raise ValidationError("API key must contain only ASCII characters", field="api_key")
    
    return api_key


def validate_object_id(obj_id: Any) -> ObjectId:
    """Validate and convert string to MongoDB ObjectId."""
    if isinstance(obj_id, ObjectId):
        return obj_id
    
    if not isinstance(obj_id, str):
        raise InvalidObjectIdError(str(obj_id))
    
    try:
        return ObjectId(obj_id)
    except Exception as e:
        raise InvalidObjectIdError(obj_id)


def build_document_lookup(doc_id: Any) -> dict[str, Any]:
    """Build a MongoDB lookup that supports either legacy ObjectId or string UUID IDs."""
    if isinstance(doc_id, ObjectId):
        return {"$or": [{"_id": doc_id}, {"_id": str(doc_id)}]}

    doc_id = validate_string_field(str(doc_id), field_name="id", min_length=1, max_length=200)

    if ObjectId.is_valid(doc_id):
        return {"$or": [{"_id": doc_id}, {"_id": ObjectId(doc_id)}]}

    return {"_id": doc_id}


def validate_string_field(
    value: str,
    field_name: str,
    min_length: int = 1,
    max_length: int = 10000,
    allow_empty: bool = False,
) -> str:
    """Validate string field with length constraints."""
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be a string", field=field_name)
    
    value = value.strip()
    
    if not value and not allow_empty:
        raise ValidationError(f"{field_name} cannot be empty", field=field_name)
    
    if len(value) < min_length:
        raise ValidationError(
            f"{field_name} must be at least {min_length} characters",
            field=field_name
        )
    
    if len(value) > max_length:
        raise ValidationError(
            f"{field_name} must not exceed {max_length} characters",
            field=field_name
        )
    
    return value


def validate_query(query: str) -> str:
    """Validate search query."""
    query = validate_string_field(
        query,
        field_name="query",
        min_length=2,
        max_length=500,
    )
    
    # Remove potentially harmful characters
    query = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', query)
    
    return query


def validate_method_name(method_name: str) -> str:
    """Validate method name format."""
    method_name = validate_string_field(
        method_name,
        field_name="method_name",
        min_length=3,
        max_length=200,
    )
    
    # Allow alphanumeric, underscores, dots, parentheses for function signatures
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_.(),\s\-\[\]]*$', method_name):
        raise ValidationError(
            "method_name contains invalid characters",
            field="method_name"
        )
    
    return method_name


def validate_raw_method(raw_method: str) -> str:
    """Validate raw method code."""
    raw_method = validate_string_field(
        raw_method,
        field_name="raw_method",
        min_length=10,
        max_length=50000,
    )
    
    # Remove null bytes
    raw_method = raw_method.replace('\x00', '')
    
    return raw_method


def validate_file_size(size_bytes: int, max_size_mb: Optional[int] = None) -> int:
    """Validate file size."""
    if max_size_mb is None:
        max_size_mb = settings.MAX_UPLOAD_FILE_SIZE_MB
    
    max_size_bytes = max_size_mb * 1024 * 1024
    
    if size_bytes > max_size_bytes:
        size_mb = size_bytes / (1024 * 1024)
        raise SizeExceededError(size_mb, max_size_mb)
    
    if size_bytes == 0:
        raise FileValidationError("File is empty")
    
    return size_bytes


def validate_file_format(filename: str, allowed_extensions: Optional[list[str]] = None) -> str:
    """Validate file format by extension."""
    if not filename or not isinstance(filename, str):
        raise FileValidationError("Filename must be a non-empty string")
    
    if allowed_extensions is None:
        allowed_extensions = [".py", ".txt", ".json", ".xlsx"]
    
    # Get file extension
    if '.' not in filename:
        raise FileValidationError(f"File must have an extension: {', '.join(allowed_extensions)}")
    
    ext = '.' + filename.rsplit('.', 1)[-1].lower()
    
    if ext not in allowed_extensions:
        raise FileValidationError(
            f"File format '{ext}' not allowed. Allowed: {', '.join(allowed_extensions)}",
            details={"filename": filename, "extension": ext, "allowed": allowed_extensions}
        )
    
    return filename


def validate_content_type(content_type: Optional[str], allowed_types: Optional[list[str]] = None) -> str:
    """Validate content type."""
    if not content_type:
        raise FileValidationError("Content-Type header is required")
    
    if allowed_types is None:
        allowed_types = [
            "text/plain",
            "application/json",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/octet-stream",
        ]
    
    base_type = content_type.split(';')[0].strip()
    
    if base_type not in allowed_types:
        raise FileValidationError(
            f"Content-Type '{base_type}' not allowed",
            details={"content_type": base_type, "allowed": allowed_types}
        )
    
    return content_type


def sanitize_string(value: str) -> str:
    """Sanitize string by removing control characters and excess whitespace."""
    if not isinstance(value, str):
        return str(value)
    
    # Remove control characters
    value = ''.join(char for char in value if ord(char) >= 32 or char in '\n\r\t')
    
    # Normalize whitespace
    value = ' '.join(value.split())
    
    return value


def validate_pagination(limit: Optional[int], skip: Optional[int]) -> tuple[int, int]:
    """Validate pagination parameters."""
    max_limit = 100
    
    if limit is None:
        limit = 10
    elif limit < 1:
        raise ValidationError("limit must be >= 1", field="limit")
    elif limit > max_limit:
        raise ValidationError(f"limit must not exceed {max_limit}", field="limit")
    
    if skip is None:
        skip = 0
    elif skip < 0:
        raise ValidationError("skip must be >= 0", field="skip")
    
    return limit, skip
