"""
Data validation layer for MongoDB operations.
Ensures data consistency and integrity at the database level.
"""

from typing import Dict, Any, List

from app.core.logging import logger
from app.core.errors import validation_error, ProductionError


class ValidationError(ProductionError):
    """Validation-specific error."""
    pass


class TestCaseValidator:
    """Validates test case data before database operations."""

    REQUIRED_FIELDS = {
        "Feature": str,
        "Test Case Description": str,
    }

    OPTIONAL_FIELDS = {
        "feature": str,
        "description": str,
        "prerequisites": str,
        "steps": str,
        "keywords": list,
        "tags": list,
        "priority": str,
        "platform": str,
        "summary": str,
        "playwright_script_id": str,
        "script_framework": str,
        "script_language": str,
        "popularity": float,
    }

    VALID_PRIORITIES = {"Low", "Medium", "High", "Critical"}

    MAX_FIELD_LENGTH = 10000
    MAX_QUERY_LENGTH = 5000
    MAX_LIST_ITEMS = 100

    @classmethod
    def _validate_string(cls, field: str, value: Any) -> str:

        if not isinstance(value, str):
            raise validation_error(f"Field '{field}' must be string")

        value = value.strip()

        if not value:
            raise validation_error(f"Field '{field}' cannot be empty")

        if len(value) > cls.MAX_FIELD_LENGTH:
            raise validation_error(
                f"Field '{field}' exceeds maximum length {cls.MAX_FIELD_LENGTH}"
            )

        return value

    @classmethod
    def _validate_optional_string(cls, field: str, value: Any) -> str:

        if not isinstance(value, str):
            raise validation_error(f"Field '{field}' must be string")

        value = value.strip()

        if len(value) > cls.MAX_FIELD_LENGTH:
            raise validation_error(
                f"Field '{field}' exceeds maximum length {cls.MAX_FIELD_LENGTH}"
            )

        return value

    @classmethod
    def _validate_list(cls, field: str, value: Any) -> List[str]:

        if not isinstance(value, list):
            raise validation_error(f"Field '{field}' must be list")

        if len(value) > cls.MAX_LIST_ITEMS:
            raise validation_error(
                f"Field '{field}' exceeds max items ({cls.MAX_LIST_ITEMS})"
            )

        clean_list = []

        for item in value:

            if not isinstance(item, str):
                raise validation_error(
                    f"All elements in '{field}' must be string"
                )

            item = item.strip()

            if item:
                clean_list.append(item)

        return clean_list

    @classmethod
    def _validate_number(cls, field: str, value: Any) -> float:

        if isinstance(value, bool):
            raise validation_error(f"Field '{field}' must be numeric")

        try:
            number = float(value)
        except Exception:
            raise validation_error(f"Field '{field}' must be numeric")

        return number

    @classmethod
    def validate_create(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate test case creation."""

        clean_data: Dict[str, Any] = {}

        allowed_fields = set(cls.REQUIRED_FIELDS) | set(cls.OPTIONAL_FIELDS)

        # Reject unknown fields
        for field in data:
            if field not in allowed_fields:
                raise validation_error(f"Unknown field: {field}")

        # Required fields
        for field in cls.REQUIRED_FIELDS:

            if field not in data:
                raise validation_error(f"Missing required field: {field}")

            clean_data[field] = cls._validate_string(field, data[field])

        # Optional fields
        for field in cls.OPTIONAL_FIELDS:

            if field not in data or data[field] is None:
                continue

            value = data[field]

            if field in ["keywords", "tags"]:
                clean_data[field] = cls._validate_list(field, value)
            elif field == "popularity":
                clean_data[field] = cls._validate_number(field, value)

            else:
                clean_data[field] = cls._validate_string(field, value)

        # Priority validation
        if "priority" in clean_data:

            if clean_data["priority"] not in cls.VALID_PRIORITIES:
                raise validation_error(
                    f"Invalid priority. Must be one of: {', '.join(cls.VALID_PRIORITIES)}"
                )

        return clean_data

    @classmethod
    def validate_update(cls, data: Dict[str, Any]) -> Dict[str, Any]:

        if not data:
            raise validation_error("Update payload cannot be empty")

        clean_data: Dict[str, Any] = {}

        allowed_fields = set(cls.OPTIONAL_FIELDS)

        for field, value in data.items():

            if field not in allowed_fields:
                raise validation_error(f"Unknown field: {field}")

            if value is None:
                continue

            if field in ["keywords", "tags"]:
                clean_data[field] = cls._validate_list(field, value)
            elif field == "popularity":
                clean_data[field] = cls._validate_number(field, value)

            else:
                clean_data[field] = cls._validate_optional_string(field, value)

        if "priority" in clean_data:

            if clean_data["priority"] and clean_data["priority"] not in cls.VALID_PRIORITIES:
                raise validation_error(
                    f"Invalid priority. Must be one of: {', '.join(cls.VALID_PRIORITIES)}"
                )

        return clean_data

    @classmethod
    def validate_query(cls, query: str) -> str:

        if not isinstance(query, str):
            raise validation_error("Query must be string")

        query = query.strip()

        if not query:
            raise validation_error("Query cannot be empty")

        if len(query) < 2:
            raise validation_error("Query must be at least 2 characters")

        if len(query) > cls.MAX_QUERY_LENGTH:
            raise validation_error(
                f"Query exceeds max length ({cls.MAX_QUERY_LENGTH})"
            )

        return query


class PlaywrightScriptValidator:
    """Validates Playwright script data."""

    MAX_SCRIPT_LENGTH = 100000

    @staticmethod
    def _validate_document_id(value: str, field: str):
        if not isinstance(value, str):
            raise validation_error(f"Field '{field}' must be string")

        value = value.strip()

        if not value:
            raise validation_error(f"Field '{field}' cannot be empty")

        return value

    @classmethod
    def validate_create(cls, data: Dict[str, Any]) -> Dict[str, Any]:

        required_fields = ["testcase_id", "testcase_object_id", "script"]

        clean_data: Dict[str, Any] = {}

        for field in required_fields:

            if field not in data:
                raise validation_error(f"Missing required field: {field}")

            if not isinstance(data[field], str):
                raise validation_error(f"Field '{field}' must be string")

            value = data[field].strip()

            if not value:
                raise validation_error(f"Field '{field}' cannot be empty")

            clean_data[field] = value

        clean_data["testcase_object_id"] = cls._validate_document_id(
            clean_data["testcase_object_id"],
            "testcase_object_id",
        )

        if len(clean_data["script"]) > cls.MAX_SCRIPT_LENGTH:
            raise validation_error(
                f"Script exceeds maximum size {cls.MAX_SCRIPT_LENGTH}"
            )

        return clean_data

    @classmethod
    def validate_update(cls, data: Dict[str, Any]) -> Dict[str, Any]:

        if not data:
            raise validation_error("Update payload cannot be empty")

        clean_data: Dict[str, Any] = {}

        if "script" in data:

            if not isinstance(data["script"], str):
                raise validation_error("Script must be string")

            script = data["script"].strip()

            if not script:
                raise validation_error("Script cannot be empty")

            if len(script) > cls.MAX_SCRIPT_LENGTH:
                raise validation_error("Script exceeds maximum size")

            clean_data["script"] = script

        return clean_data
