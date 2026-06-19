from __future__ import annotations

import logging
from typing import Optional, Dict, Any

from app.core.llm_executor import LLMExecutor
from app.core.dom_pruner import DomPruner
from app.core.prompts import build_repair_explanation_prompt
from app.models.llm_structured import RepairExplanation




__all__ = ["RepairExplanationService"]


logger = logging.getLogger("llm.repair.explainer")


class RepairExplanationService:
    """Generates a human-readable explanation of why an automated Playwright repair worked.

    Uses Gemini structured output (response_mime_type=application/json +
    response_schema=RepairExplanation) so the model is constrained to emit
    schema-valid JSON at the API level — no prompt-level JSON instructions,
    no post-hoc regex extraction.
    """

    DEFAULT_DOM_SNIPPET_MAX_CHARS: int = 800

    FAILURE_TYPE_ENUM = (
        "LOCATOR_CHANGE",
        "ELEMENT_NOT_VISIBLE",
        "DOM_CHANGE",
        "TIMING_ISSUE",
        "ASSERTION_CHANGE",
        "UNKNOWN",
    )

    def __init__(
        self,
        llm: Optional[LLMExecutor] = None,
        dom_snippet_max_chars: Optional[int] = None,
    ) -> None:
        """Initialize the service.

        Args:
            llm: Optional LLMExecutor instance. If omitted, the singleton is used.
            dom_snippet_max_chars: Max chars to include from the pruned DOM in the prompt.
        """
        self.llm = llm or LLMExecutor.get_instance()
        if dom_snippet_max_chars is None:
            self.DOM_SNIPPET_MAX_CHARS = self.DEFAULT_DOM_SNIPPET_MAX_CHARS
        else:
            self.DOM_SNIPPET_MAX_CHARS = int(dom_snippet_max_chars)

    # ==================================================
    # PUBLIC API
    # ==================================================

    async def generate_explanation(
        self,
        *,
        step_id: str,
        step_intent: str,
        original_code: str,
        repaired_code: str,
        error_text: str,
        dom_snapshot: Optional[str] = None,
        error_image_bytes: Optional[bytes] = None,
        framework: str = "playwright",
    ) -> Optional[Dict[str, Any]]:
        """Generate a JSON explanation of why a repair fixed a Playwright step.

        Returns:
            A dict if parsing succeeds, otherwise None.
        """
        # Input validation - keep this light so behaviour matches previous implementation
        step_id = (step_id or "").strip()
        step_intent = (step_intent or "").strip()

        prompt = self._build_prompt(
            step_id=step_id,
            step_intent=step_intent,
            original_code=original_code or "",
            repaired_code=repaired_code or "",
            error_text=error_text or "",
            dom_snapshot=dom_snapshot,
            framework=framework,
        )

        try:
            if error_image_bytes:
                raw = await self.llm.run_multimodal_modifier_structured(
                    prompt=prompt,
                    image_bytes=error_image_bytes,
                    schema=RepairExplanation,
                )
            else:
                raw = await self.llm.run_modifier_structured(prompt, RepairExplanation)
        except Exception:
            logger.exception("EXPLANATION LLM FAILURE for step_id=%s", step_id)
            return None

        if not raw:
            logger.debug("LLM returned empty response for step_id=%s", step_id)
            return None

        truncated = raw if len(raw) <= 2000 else raw[:2000] + "...<truncated>"
        logger.debug("REPAIR EXPLANATION RAW OUTPUT (truncated) = %s", truncated)

        try:
            result = RepairExplanation.model_validate_json(raw)
        except Exception:
            logger.error("EXPLANATION STRUCTURED PARSE FAILED for step_id=%s", step_id)
            return None

        return result.model_dump()

    def _normalize_explanation_schema(self, parsed: Dict[str, Any]) -> Dict[str, Any]:
        # Schema is now enforced by RepairExplanation at the Gemini API level;
        # this method is retained only for any external callers that may reference it.
        return parsed

    # ==================================================
    # PROMPT
    # ==================================================

    def _build_prompt(
        self,
        *,
        step_id: str,
        step_intent: str,
        original_code: str,
        repaired_code: str,
        error_text: str,
        dom_snapshot: Optional[str],
        framework: str = "playwright",
    ) -> str:
        """Construct the prompt sent to the LLM.

        This keeps the same schema and content as the original, while making
        the prompt string creation clearer and safer to read in code.
        """
        pruned_dom = (
            DomPruner.prune(dom_snapshot, None, framework=framework)
            if dom_snapshot
            else None
        )
        dom_block = (
            (pruned_dom[: self.DOM_SNIPPET_MAX_CHARS] if pruned_dom else "N/A")
        )

        return build_repair_explanation_prompt(
            step_id=step_id,
            step_intent=step_intent,
            original_code=original_code,
            repaired_code=repaired_code,
            error_text=error_text,
            dom_snapshot=dom_block,
            framework=framework,
        )


