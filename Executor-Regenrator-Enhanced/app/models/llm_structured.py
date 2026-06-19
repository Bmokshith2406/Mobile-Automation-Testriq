from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class VerifierResult(BaseModel):
    """Structured output schema for the step verifier LLM call."""

    verdict: Literal["correct", "incorrect"]
    reason: str


class RepairExplanation(BaseModel):
    """Structured output schema for the repair explanation LLM call."""

    failure_reason: str
    repair_action: str
    why_previous_failed: str
    why_repair_was_selected: str
    rerun_result: str = "pending_rerun"
    execution_passed: Optional[bool] = None
    failure_type: Literal[
        "LOCATOR_CHANGE",
        "ELEMENT_NOT_VISIBLE",
        "DOM_CHANGE",
        "TIMING_ISSUE",
        "ASSERTION_CHANGE",
        "UNKNOWN",
    ]
    summary: str
