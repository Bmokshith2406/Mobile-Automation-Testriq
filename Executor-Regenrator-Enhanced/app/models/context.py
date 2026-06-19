# app/models/context.py

from typing import Optional
from pydantic import BaseModel, Field


class StepRepairContext(BaseModel):
    """
    Diagnostic-only context for STEP REPAIR.

    NOT executable
    NOT part of StepCIR
    NEVER mutable by LLMs

    Used for:
    - Failure analysis
    - CIR construction diagnostics
    - Audit / observability
    """

    # Legacy or reference code that informed intent understanding
    reference_code: Optional[str] = Field(
        default=None,
        description="Original step code or legacy automation snippet"
    )

    # Script fragment or test file that matched this step (if any)
    matched_script: Optional[str] = Field(
        default=None,
        description="Matched script or test reference used during repair"
    )

    # Reason why deterministic repair was skipped or failed
    skip_reason: Optional[str] = Field(
        default=None,
        description="Reason deterministic repair was not applicable"
    )

    # Reason why the step was marked non-repairable
    rejection_reason: Optional[str] = Field(
        default=None,
        description="Why the step was rejected as non-repairable"
    )

    model_config = {
        "extra": "forbid"
    }
