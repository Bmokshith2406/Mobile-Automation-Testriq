#app/models/test_case.py

from typing import List, Optional, Literal
from pydantic import BaseModel, Field, model_validator

from app.models.appium import AppiumConfig
from app.models.matched_script import MatchedScript


_ID_PATTERN = r"^[A-Za-z0-9_\-]+$"


class Prerequisite(BaseModel):
    """
    Test case prerequisite.
    Represents setup or precondition logic.
    """

    prerequisite_id: str = Field(
        ...,
        min_length=1,
        pattern=_ID_PATTERN,
        description="Unique identifier for the prerequisite",
    )

    description: str = Field(
        ...,
        min_length=1,
        description="Human-readable prerequisite description",
    )

    matched_script: Optional[MatchedScript] = Field(
        default=None,
        description="Optional reference script for this prerequisite",
    )

    model_config = {
        "str_strip_whitespace": True,
        "extra": "forbid",
    }


class Step(BaseModel):
    """
    Single test execution step.
    Order matters.
    """

    step_id: str = Field(
        ...,
        min_length=1,
        pattern=_ID_PATTERN,
        description="Unique identifier for the step (authoring-time)",
    )

    description: str = Field(
        ...,
        min_length=1,
        description="Human-readable step description",
    )

    expected_outcome: Optional[str] = Field(
        default=None,
        description="Optional expected outcome for validation",
    )

    matched_script: Optional[MatchedScript] = Field(
        default=None,
        description="Optional reference script for this step",
    )

    max_retries: Optional[int] = Field(
        default=None,
        ge=0,
        le=10,
        description="Per-step override for max retry count",
    )

    model_config = {
        "str_strip_whitespace": True,
        "extra": "forbid",
    }

    @model_validator(mode="after")
    def normalize_expected_outcome(self):
        # Treat empty strings as None
        if self.expected_outcome is not None and not self.expected_outcome.strip():
            self.expected_outcome = None
        return self


class TestCase(BaseModel):
    """
    Authoritative input object for script generation.

    Notes:
    - Step order is preserved and significant
    - Identifiers must be unique within the test case
    """

    test_case_id: str = Field(
        ...,
        min_length=1,
        pattern=_ID_PATTERN,
        description="Unique test case identifier",
    )

    description: str = Field(
        ...,
        min_length=1,
        description="Overall test case description",
    )

    target_framework: Optional[Literal["playwright", "selenium", "cypress", "appium"]] = Field(
        default=None,
        description="Target framework for the script (e.g. playwright, selenium, cypress, appium)",
    )

    appium_config: Optional[AppiumConfig] = Field(
        default=None,
        description=(
            "Optional Appium launch defaults. Runtime device/app capabilities "
            "can be supplied later by Executor-Regenerator."
        ),
    )

    prerequisites: List[Prerequisite] = Field(
        default_factory=list,
        description="List of test prerequisites",
    )

    steps: List[Step] = Field(
        ...,
        min_length=1,
        description="Ordered list of test steps",
    )

    teardown_steps: List[Step] = Field(
        default_factory=list,
        description="Optional teardown steps run after test",
    )

    model_config = {
        "str_strip_whitespace": True,
        "extra": "forbid",
    }

    @model_validator(mode="after")
    def validate_unique_ids(self):
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("Duplicate step_id values are not allowed")

        prereq_ids = [p.prerequisite_id for p in self.prerequisites]
        if len(prereq_ids) != len(set(prereq_ids)):
            raise ValueError("Duplicate prerequisite_id values are not allowed")

        return self

    @model_validator(mode="after")
    def validate_appium_config(self):
        framework = (self.target_framework or "").lower().strip()

        if framework and framework != "appium" and self.appium_config is not None:
            raise ValueError("appium_config is only valid for target_framework=appium")

        return self
