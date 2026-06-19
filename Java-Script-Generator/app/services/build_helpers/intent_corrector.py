from typing import Optional
import logging
import difflib
import re

from app.core.llm_executor import get_llm_executor, LLMExecutor
from app.core.llm_json import generate_json
from app.core.json_schemas import INTENT_PARAMETER_CORRECTION_SCHEMA
from app.prompts.templates import PromptTemplates

logger = logging.getLogger("intent_corrector")


class IntentCorrectionError(Exception):
    pass


class IntentCorrector:
    """
    CIR-SAFE LLM PARAMETER CORRECTOR

    HARD GUARANTEES:
    - NEVER changes action type
    - NEVER changes control flow
    - NEVER changes structure
    - NEVER changes locator strategies
    - NEVER changes selectors
    - NEVER invents values
    - ONLY modifies explicitly stated parameters
    - Idempotent (running twice yields same result)
    - Syntax-safe
    - Soft-fail only
    """

    CORRECTOR_VERSION = "CIR_SAFE_1.0"

    def __init__(self, llm: Optional[LLMExecutor] = None):
        self.llm = llm or get_llm_executor()
        logger.info("IntentCorrector initialized | mode=CIR_SAFE")

    # ==================================================
    # PUBLIC ENTRY
    # ==================================================

    async def correct(
        self,
        *,
        intent: str,
        expected: Optional[str],
        raw_code: str,
    ) -> str:
        """
        Returns corrected raw_code.
        If no correction is needed or safety checks fail, returns original raw_code.
        """

        if not intent or not raw_code:
            return raw_code

        prompt = PromptTemplates.intent_parameter_correction(
            intent=intent,
            raw_code=raw_code,
            expected=expected,
        )

        try:
            result = await generate_json(
                prompt,
                purpose="intent_parameter_correction",
                schema=INTENT_PARAMETER_CORRECTION_SCHEMA,
            )
            logger.debug("INTENT CORRECTOR RAW LLM RESPONSE | %s", result)
        except Exception:
            logger.exception("LLM intent correction failed")
            return raw_code

        if not isinstance(result, dict):
            return raw_code

        corrected_code = result.get("corrected_code")
        changed = result.get("changed")
        reason = result.get("reason")

        if not isinstance(corrected_code, str):
            return raw_code

        if not isinstance(changed, bool):
            return raw_code

        if not isinstance(reason, str):
            return raw_code

        corrected_code = corrected_code.strip()

        # --------------------------------------------------
        # SAFETY FIREWALL
        # --------------------------------------------------

        if not changed:
            return raw_code

        if not self._is_structure_preserved(raw_code, corrected_code):
            logger.error("INTENT CORRECTOR BLOCKED | structure change detected")
            return raw_code

        if self._diff_contains_locator_mutation(raw_code, corrected_code):
            logger.error("INTENT CORRECTOR BLOCKED | locator mutation detected")
            return raw_code

        logger.info(
            "INTENT CORRECTED | reason=%s",
            reason.strip(),
        )

        return corrected_code

    # ==================================================
    # SAFETY FIREWALLS
    # ==================================================

    def _is_structure_preserved(self, before: str, after: str) -> bool:
        before_lines = [l for l in before.strip().splitlines() if l.strip()]
        after_lines = [l for l in after.strip().splitlines() if l.strip()]

        if len(before_lines) != len(after_lines):
            return False

        CONTROL_FLOW = {"if ", "for ", "while ", "try:", "with ", "def ", "class "}
        before_cf = sum(1 for l in before_lines if any(l.strip().startswith(k) for k in CONTROL_FLOW))
        after_cf = sum(1 for l in after_lines if any(l.strip().startswith(k) for k in CONTROL_FLOW))
        if before_cf != after_cf:
            return False

        return True

    def _diff_contains_locator_mutation(self, before: str, after: str) -> bool:
        LOCATOR_PATTERNS = [
            re.compile(r'\bBy\.\w+\s*,'),
            re.compile(r'\bget_by_\w+\('),
            re.compile(r'\bfind_element\s*\('),
            re.compile(r'\blocator\s*\('),
            re.compile(r'\bcy\.get\s*\('),
            re.compile(r'AppiumBy\.\w+\s*,'),
            re.compile(r'//[a-z]+\['),
            re.compile(r'\bcss='),
            re.compile(r'\[data-testid'),
            re.compile(r'\bquerySelector\s*\('),
        ]

        before_lines = before.splitlines()
        after_lines = after.splitlines()
        diff = list(difflib.ndiff(before_lines, after_lines))

        for line in diff:
            if not line.startswith("+") and not line.startswith("-"):
                continue
            content = line[2:]
            if any(pattern.search(content) for pattern in LOCATOR_PATTERNS):
                return True

        return False


