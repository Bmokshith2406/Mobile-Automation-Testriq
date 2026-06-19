from pydantic import BaseModel, Field
from typing import Optional, List


class ErrorClassification(BaseModel):
    """
    High-level categorization of the failure.
    Used for action classification and repair context.
    """
    type: str = Field(
        ...,
        description="Normalized error type (e.g. LOCATOR_NOT_FOUND, ASSERTION_FAILED)",
    )
    subtype: Optional[str] = Field(
        None,
        description="Sub-categorization of the error (e.g. timeout)",
    )
    confidence: Optional[float] = Field(
        None,
        description="Confidence score of classification",
    )


class ErrorDetails(BaseModel):
    """
    Concrete runtime failure details.
    Passed verbatim to StepModifier.
    """
    message: str = Field(
        ...,
        description="Primary runtime error message",
    )
    failed_api: Optional[str] = Field(
        None,
        description="Playwright API that failed (if available)",
    )
    timestamp: Optional[str] = Field(
        None,
        description="Failure timestamp (optional, informational only)",
    )


class Artifacts(BaseModel):
    """
    Runtime artifacts captured at failure time.
    Used ONLY for CIR evidence extraction and classification.

    IMPORTANT:
    - error_image_bytes is INTERNAL ONLY
    - It is injected by backend, never from client
    """

    dom_snapshot: Optional[str] = Field(
        None,
        description="Serialized DOM snapshot at failure time",
    )

    page_url: Optional[str] = Field(
        None,
        description="Current page URL at failure time",
    )

    # 🔒 INTERNAL FIELD — NOT PART OF API CONTRACT
    error_image_bytes: Optional[bytes] = Field(
        None,
        exclude=True,
        repr=False,
    )

    error_text: Optional[str] = None
    traceback_text: Optional[str] = None

class StepRepairRequest(BaseModel):
    """
    Canonical payload for STEP-LEVEL REPAIR.

    One request represents exactly ONE failed step.
    """

    step_id: str = Field(
        ...,
        description="Unique identifier of the failed step",
    )

    step_intent: str = Field(
        ...,
        description="Human-readable intent of the step",
    )

    original_code: str = Field(
        ...,
        description="Original Playwright code that failed",
    )

    error_classification: ErrorClassification = Field(
        ...,
        description="High-level failure classification",
    )

    error_details: ErrorDetails = Field(
        ...,
        description="Runtime error information",
    )

    traceback: Optional[str] = Field(
        None,
        description="Full stack trace (used ONLY by StepModifier)",
    )

    artifacts: Optional[Artifacts] = Field(
        None,
        description="Runtime artifacts for CIR evidence extraction",
    )
    
    previous_failed_codes: Optional[List[str]] = Field(
        default=None,
        description="All previously failed versions of this step in chronological order",
    )
    
    framework: str = Field(
        default="playwright",
        description="Active automation framework identified for this execution run",
    )
