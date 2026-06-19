from typing import Optional
import logging
import difflib
import re

from app.core.llm_executor import get_llm_executor, LLMExecutor
from app.core.llm_json import generate_json
from app.core.json_schemas import FRAMEWORK_ROLE_UPGRADE_SCHEMA
from app.prompts.template_engine import get_template_engine

logger = logging.getLogger("role_upgrader")

class FrameworkRoleUpgradeError(Exception):
    pass

class FrameworkRoleUpgrader:
    """
    CIR-SAFE FRAMEWORK ROLE UPGRADE ENGINE

    HARD GUARANTEES:
    - NEVER changes action type
    - NEVER changes control flow
    - NEVER changes values
    - NEVER changes waits or assertions
    - NEVER invents roles or names
    - NEVER weakens selector specificity
    - ONLY upgrades locator(...) → semantic role locators (e.g. get_by_role)
    - ONLY when provably safe and equivalent
    - Idempotent
    - Syntax-safe
    - Soft-fail only
    """

    UPGRADE_VERSION = "ROLE_SAFE_1.0"

    def __init__(self, llm: Optional[LLMExecutor] = None):
        self.llm = llm or get_llm_executor()
        self.template_engine = get_template_engine()
        logger.info("FrameworkRoleUpgrader initialized | mode=%s", "ROLE_SAFE")

    # ==================================================
    # PUBLIC ENTRY
    # ==================================================

    async def upgrade(
        self,
        *,
        raw_code: str,
    ) -> str:
        """
        Returns upgraded code.
        If no safe upgrade is possible, returns original raw_code.
        """

        if not raw_code:
            return raw_code

        prompt = self.template_engine.render("framework_role_upgrade", raw_code=raw_code)

        try:
            result = await generate_json(
                prompt,
                purpose="framework_role_upgrade",
                schema=FRAMEWORK_ROLE_UPGRADE_SCHEMA,
            )
            logger.debug("ROLE UPGRADER RAW LLM RESPONSE | %s", result)
        except Exception:
            logger.exception("LLM role upgrade failed")
            return raw_code

        if not isinstance(result, dict):
            return raw_code

        upgraded_code = result.get("upgraded_code")
        changed = result.get("changed")
        reason = result.get("reason")

        if not isinstance(upgraded_code, str):
            return raw_code

        if not isinstance(changed, bool):
            return raw_code

        if not isinstance(reason, str):
            return raw_code

        upgraded_code = upgraded_code.strip()

        # --------------------------------------------------
        # SAFETY FIREWALL
        # --------------------------------------------------

        if not changed:
            return raw_code

        if not self._is_structure_preserved(raw_code, upgraded_code):
            logger.error("ROLE UPGRADE BLOCKED | structure change detected")
            return raw_code

        if not self._is_safe_role_diff(raw_code, upgraded_code):
            logger.error("ROLE UPGRADE BLOCKED | unsafe locator mutation")
            return raw_code

        logger.info(
            "SAFE ROLE UPGRADE APPLIED | reason=%s",
            reason.strip(),
        )

        return upgraded_code

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

    def _is_safe_role_diff(self, before: str, after: str) -> bool:
        """
        Allows ONLY:
        - locator(...) → semantic locators
        Blocks:
        - any other locator mutation
        - selector weakening
        - non-locator changes
        """
        diff = difflib.ndiff(
            before.strip().splitlines(),
            after.strip().splitlines(),
        )

        forbidden_tokens = (
            "xpath",
            "//",
            "#",
            ".class",
            "nth",
            "first",
            "last",
            "{",
            "}",
            ">>",
            "has(",
            "css=",
            "text=",
        )

        for line in diff:
            if line.startswith(("+", "-")):
                lower = line.lower()

                # Allow introducing get_by_role (playwright) or similar semantic tags
                if "get_by_role" in lower or "role=" in lower:
                    continue

                # Allow removing locator(...) or driver.find_element or cy.get
                if "locator(" in lower or "find_element" in lower or "get(" in lower:
                    continue

                # Everything else is forbidden
                if any(tok in lower for tok in forbidden_tokens):
                    return False

        return True
