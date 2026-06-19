# app/models/extraction.py

from pydantic import BaseModel, Field, model_validator
from typing import Optional, Any

from app.models.cir import (
    LocatorStrategy,
    AssertionType,
    StepWait,
    CIRLocator,
)


# ==================================================
# EXTRACTION MODELS (EVIDENCE-LEVEL)
# ==================================================

class ExtractedLocator(BaseModel):
    """
    Normalized locator extracted from evidence.

    Evidence may include:
    - Original step code
    - DOM snapshot
    - Failure traceback
    - Screenshot-derived hints

    NOT executable
    NOT a CIR
    """

    strategy: LocatorStrategy = Field(
        ..., description="Normalized locator strategy"
    )
    value: str = Field(
        ..., min_length=1, description="Locator value"
    )

    # --------------------------------------------------
    # CONVERSION → CIR (EXPLICIT, SAFE)
    # --------------------------------------------------

    def to_cir(self) -> CIRLocator:
        """
        Convert extracted locator into executable CIR locator.

        This is the ONLY allowed conversion point.
        """
        return CIRLocator(
            locator_strategy=self.strategy,
            locator_value=self.value,
        )


class ExtractedValue(BaseModel):
    """
    Normalized value extracted for input actions.
    """

    value: Optional[str] = Field(
        default=None, description="Value associated with the step (e.g. typed text)"
    )
    text: Optional[str] = Field(
        default=None, description="Text equivalent of the value"
    )
    is_sensitive: Optional[bool] = Field(
        default=None, description="Whether the value is sensitive"
    )

    @model_validator(mode="before")
    @classmethod
    def sync_text_and_value(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "text" in data and "value" not in data:
                data["value"] = data["text"]
            elif "value" in data and "text" not in data:
                data["text"] = data["value"]
        return data


class ExtractedAssertion(BaseModel):
    """
    Normalized assertion facts extracted from evidence.

    This is an intermediate representation used by:
    - FailureAnalyzer
    - CIRBuilder

    NOT executable
    NOT a StepCIR
    """

    type: AssertionType = Field(
        ..., description="Type of assertion"
    )

    expected: Optional[str] = Field(
        default=None,
        description="Expected value if required by assertion type",
    )

    locator: Optional[ExtractedLocator] = Field(
        default=None,
        description="Target locator for element-based assertions",
    )

    wait: Optional[StepWait] = Field(
        default=None,
        description="Suggested deterministic wait before assertion",
    )

    model_config = {
        "extra": "forbid"
    }
