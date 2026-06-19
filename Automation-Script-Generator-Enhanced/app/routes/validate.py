# app/routes/validate.py
"""
Dry-Run Validation Endpoint

Validates a TestCase by running only CIR build and validation,
without code generation or assembly. Returns validation summary.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List
import logging

from app.models.test_case import TestCase
from app.services.cir_builder import CIRBuilder
from app.services.validator import CIRValidator, CIRValidationError

router = APIRouter()
logger = logging.getLogger("api.validate")

_cir_builder = CIRBuilder()
_validator = CIRValidator()


class ValidateRequest(BaseModel):
    test_case: TestCase = Field(..., description="Test case to validate")
    model_config = {"extra": "forbid"}


class ValidateResponse(BaseModel):
    valid: bool
    cir_summary: dict
    warnings: List[str] = Field(default_factory=list)
    error: Optional[str] = None


@router.post("/", summary="Validate Test Case (Dry Run)", response_model=ValidateResponse)
async def validate_test_case(body: ValidateRequest) -> ValidateResponse:
    """
    Validate a test case by building the CIR without generating code.
    Returns a summary of what would be generated.
    """
    test_case = body.test_case
    warnings: List[str] = []

    try:
        cir, context_map = await _cir_builder.build(test_case)
    except Exception as e:
        return ValidateResponse(
            valid=False,
            cir_summary={},
            error=str(e),
        )

    # Validate CIR
    validation_errors = []
    all_blocks = cir.setup + cir.steps + cir.teardown
    try:
        _validator.validate_blocks(cir.setup)
        _validator.validate_blocks(cir.steps)
        _validator.validate_blocks(cir.teardown)
    except CIRValidationError as e:
        validation_errors.append(str(e))

    # Check for ambiguous steps
    for block in cir.steps:
        if len(block.intent.strip().split()) <= 2:
            warnings.append(
                f"Step '{block.block_id}' has a very short intent — may be ambiguous: '{block.intent}'"
            )

    if validation_errors:
        return ValidateResponse(
            valid=False,
            cir_summary={
                "setup_blocks": len(cir.setup),
                "step_blocks": len(cir.steps),
                "teardown_blocks": len(cir.teardown),
            },
            warnings=warnings,
            error="; ".join(validation_errors),
        )

    return ValidateResponse(
        valid=True,
        cir_summary={
            "setup_blocks": len(cir.setup),
            "step_blocks": len(cir.steps),
            "teardown_blocks": len(cir.teardown),
            "total_actions": sum(len(b.actions) for b in all_blocks),
        },
        warnings=warnings,
    )
