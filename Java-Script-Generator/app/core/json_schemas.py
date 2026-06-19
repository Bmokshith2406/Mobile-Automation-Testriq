# app/core/json_schemas.py
"""
JSON Schemas for all structured LLM outputs.

Defined in standard JSON Schema format (draft-07 compatible).
Nullable fields use anyOf: [{"type": "T"}, {"type": "null"}].

Provider-specific adapters live in each provider — these schemas are the
single source of truth consumed by generate_json() callers.
"""
from typing import Any, Dict

_NS = {"anyOf": [{"type": "string"}, {"type": "null"}]}  # nullable string shorthand

CLASSIFICATION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "action_type": {"type": "string"},
        "confidence": {"type": "integer"},
        "reasoning": {"type": "string"},
    },
    "required": ["action_type", "confidence", "reasoning"],
    "additionalProperties": False,
}

LOCATOR_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "locator_strategy": _NS,
        "locator_value": _NS,
        "confidence": {"type": "integer"},
    },
    "required": ["locator_strategy", "locator_value", "confidence"],
    "additionalProperties": False,
}

TYPE_VALUE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "value": _NS,
        "confidence": {"type": "integer"},
    },
    "required": ["value", "confidence"],
    "additionalProperties": False,
}

SELECT_VALUE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "value": _NS,
        "mode": {"type": "string"},
        "confidence": {"type": "integer"},
    },
    "required": ["value", "mode", "confidence"],
    "additionalProperties": False,
}

ASSERT_EXTRACTION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "assert_type": {"type": "string"},
        "locator_strategy": _NS,
        "locator_value": _NS,
        "expected_value": _NS,
        "confidence": {"type": "integer"},
    },
    "required": ["assert_type", "locator_strategy", "locator_value", "expected_value", "confidence"],
    "additionalProperties": False,
}

STEP_DECOMPOSITION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "atomic_steps": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["atomic_steps"],
    "additionalProperties": False,
}

FRAMEWORK_ROLE_UPGRADE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "upgraded_code": {"type": "string"},
        "changed": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["upgraded_code", "changed", "reason"],
    "additionalProperties": False,
}

STEP_VERIFICATION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "reason"],
    "additionalProperties": False,
}

INTENT_PARAMETER_CORRECTION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "corrected_code": {"type": "string"},
        "changed": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["corrected_code", "changed", "reason"],
    "additionalProperties": False,
}
