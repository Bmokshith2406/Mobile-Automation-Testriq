#app/models/matched_script.py

from pydantic import BaseModel, Field, model_validator
from typing import Literal


class MatchedScript(BaseModel):
    """
    Reference script attached to a step or prerequisite.

    - Used ONLY as behavioral reference
    - NEVER executed directly
    - Treated as immutable input
    """

    language: Literal["python", "javascript"] = Field(
        ...,
        description="Language of the reference script",
    )

    framework: Literal["selenium", "playwright", "cypress", "appium"] = Field(
        ...,
        description="Automation framework used in the reference script",
    )

    raw_code: str = Field(
        ...,
        min_length=5,
        description="Raw script code used as reference",
    )

    model_config = {
        "str_strip_whitespace": True,
        "extra": "forbid",
        "frozen": True,  # 🔒 Immutable once created
    }

    @model_validator(mode="after")
    def validate_raw_code(self):
        # Prevent meaningless placeholders
        lowered = self.raw_code.lower()
        if lowered in {"todo", "# todo", "// todo", "pass"}:
            raise ValueError("raw_code must contain meaningful reference code")

        return self

