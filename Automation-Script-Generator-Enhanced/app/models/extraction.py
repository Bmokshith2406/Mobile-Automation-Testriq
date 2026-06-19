#app/models/extraction.py

from pydantic import BaseModel, Field
from typing import Optional

from app.models.cir import (
    LocatorStrategy,
    AssertionType,
    CIRWait,
)


class ExtractedLocator(BaseModel):
    """
    Normalized locator extracted from LLM output.
    Must already be CIR-safe.
    """
    locator_strategy: LocatorStrategy = Field(
        ..., description="Normalized locator strategy"
    )
    locator_value: str = Field(
        ..., min_length=1, description="Locator value"
    )


class ExtractedValue(BaseModel):
    """
    Normalized input or selection value extracted from LLM output.

    For SELECT actions, `mode` determines how the value should be applied:
    - "value" → select_option("x")
    - "index" → select_option(index=0)
    - "label" → select_option(label="Savings")
    """

    value: str = Field(
        ..., min_length=0, description="Value to be used"
    )

    mode: Optional[str] = Field(
        default="value",
        description="Interpretation mode: value | index | label",
    )



class ExtractedAssertion(BaseModel):
    """
    Normalized assertion extracted from LLM output.
    Used between extractor layer and CIRBuilder.
    """

    assert_type: AssertionType = Field(
        ..., description="Type of assertion"
    )

    expected_value: Optional[str] = Field(
        default=None,
        description="Expected value for assertion (if applicable)",
    )

    locator: Optional[ExtractedLocator] = Field(
        default=None,
        description="Target locator for element-based assertions",
    )

    wait: Optional[CIRWait] = Field(
        default=None,
        description="Deterministic wait before assertion execution",
    )

