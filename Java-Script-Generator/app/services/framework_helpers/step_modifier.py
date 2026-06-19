from typing import Optional, List
import logging
import re
import asyncio
import time

from app.core.llm_executor import get_llm_executor, LLMExecutor
from app.prompts.template_engine import get_template_engine

logger = logging.getLogger("step_modifier")

LLM_MAX_RETRIES = 2
LLM_BACKOFF_BASE = 0.75
LLM_TIMEOUT_SEC = 25


class StepModifier:
    """
    SAFETY-ONLY STEP MODIFIER (FRAMEWORK AGNOSTIC)

    Invariants:
    - CIR is the semantic source of truth
    - Modifier is NOT a semantic engine
    - Modifier NEVER infers intent
    - Modifier NEVER invents actions
    - Modifier NEVER removes actions
    - Modifier NEVER reorders actions
    - Modifier NEVER changes action types
    - Modifier MAY repair locators
    - Modifier MAY repair API usage
    - Modifier ONLY adds safety mechanics
    """

    _FORBIDDEN_PATTERNS = (
        r"async_playwright",
        r"\bbrowser\s*=",
        r"\bcontext\s*=",
        r"\bpage\s*=",
        r"^\s*import\s+",
        r"\basync\s+def\b",
        r"^\s*def\b",
        r"^\s*class\b",
        r"\btry\s*:",
        r"\bexcept\b",
        r"\bfinally\b",
        r"^\s*for\s+",
        r"^\s*while\s+",
    )

    _UNSAFE_WAIT_PATTERN = re.compile(
        r"""await\s+
            page\.locator\((?P<selector>[^)]+)\)
            \.wait_for\([^)]*\)
        """,
        re.VERBOSE,
    )

    _DIRECT_PAGE_CLICK = re.compile(
        r"""await\s+page\.click\((?P<selector>[^)]+)\)"""
    )

    _DIRECT_PAGE_FILL = re.compile(
        r"""await\s+page\.fill\(\s*(?P<selector>[^,]+)\s*,\s*(?P<value>.+?)\s*\)\s*$"""
    )

    def __init__(self, llm: Optional[LLMExecutor] = None):
        self.llm = llm or get_llm_executor()
        self.template_engine = get_template_engine()
        logger.info("StepModifier initialized | mode=SAFETY_ONLY")

    # ==================================================
    # PUBLIC ENTRY
    # ==================================================

    async def modify(
        self,
        *,
        intent: str,
        generated_code: str,
        matched_script: Optional[str],
        reason: Optional[str],
        verification_mode: Optional[str],
    ) -> str:

        start_ts = time.monotonic()
        code = (generated_code or "").strip()

        if not code:
            return code

        # --------------------------------------------------
        # 1️⃣ STRUCTURAL NORMALIZATION (SAFE ONLY)
        # --------------------------------------------------

        code = self._apply_structural_normalization(code)
        self._assert_no_forbidden_input_mechanics(code)

        original_sig = self._semantic_signature(code)

        # --------------------------------------------------
        # 2️⃣ LLM SAFETY REPAIR
        # --------------------------------------------------

        llm_result = await self._run_llm_completion(
            intent=intent,
            original_code=code,
            matched_script=None if verification_mode == "INTENT_ONLY" else matched_script,
            reason=reason,
            verification_mode=verification_mode,
        )

        if not llm_result:
            return code

        sanitized = self._sanitize_llm_output(llm_result)
        if not sanitized:
            return code

        self._assert_no_forbidden_input_mechanics(sanitized)

        # 🔒 STRUCTURAL (NOT STRING) ORDER PRESERVATION
        if not self._preserves_structure(code, sanitized):
            logger.warning("STEP MODIFIER REJECTED | structural violation")
            return code

        new_sig = self._semantic_signature(sanitized)

        try:
            self._assert_action_type_preserved(original_sig, new_sig)
        except AssertionError as e:
            logger.warning("STEP MODIFIER REJECTED | %s", e)
            return code

        logger.warning(
            "STEP MODIFIER ACCEPTED | safety-only | duration=%.2fs",
            time.monotonic() - start_ts,
        )

        return sanitized

    # ==================================================
    # STRUCTURAL NORMALIZATION (NON-SEMANTIC)
    # ==================================================

    def _apply_structural_normalization(self, code: str) -> str:
        lines: List[str] = []
        rewritten = False

        for line in code.splitlines():

            # Unsafe wait → safe selector wait
            m = self._UNSAFE_WAIT_PATTERN.search(line)
            if m and m.group("selector"):
                lines.append(f"await page.wait_for_selector({m.group('selector')})")
                rewritten = True
                continue

            # Direct page.click → locator-based click
            m = self._DIRECT_PAGE_CLICK.search(line)
            if m:
                s = m.group("selector")
                lines.extend([
                    f"locator = page.locator({s})",
                    "target = locator.first",
                    "await target.scroll_into_view_if_needed()",
                    "await target.click()",
                ])
                rewritten = True
                continue

            # Direct page.fill → locator-based fill
            m = self._DIRECT_PAGE_FILL.search(line)
            if m:
                s, v = m.group("selector"), m.group("value")
                lines.extend([
                    f"locator = page.locator({s})",
                    "target = locator.first",
                    "await target.scroll_into_view_if_needed()",
                    f"await target.fill({v})",
                ])
                rewritten = True
                continue

            lines.append(line)

        return "\n".join(lines).strip() if rewritten else code

    # ==================================================
    # SEMANTIC SIGNATURE (LOCKED)
    # ==================================================

    def _semantic_signature(self, code: str) -> list[str]:
        sig = []

        for line in code.splitlines():
            l = line.strip()

            if ".click(" in l or "click()" in l:
                sig.append("click")

            elif ".clear()" in l or ".fill('')" in l or '.fill("")' in l:
                sig.append("clear")

            elif ".fill(" in l or "send_keys(" in l or "type(" in l:
                sig.append("type")

            elif ".select_option" in l or "select_by_" in l or "cy.get(" in l and "select(" in l:
                sig.append("select")

            elif (
                "page.goto(" in l
                or "go_back(" in l
                or "go_forward(" in l
                or "page.reload(" in l
                or "driver.get(" in l
                or "cy.visit(" in l
            ):
                sig.append("navigate")

            elif "to_have_text" in l or "assert " in l or ".should(" in l:
                sig.append("assert")

            elif "to_be_visible" in l or "is_displayed" in l:
                # safety assert → ignore
                pass

        return sig

    def _assert_action_type_preserved(self, original_sig: list[str], new_sig: list[str]) -> None:
        if len(original_sig) != len(new_sig):
            raise AssertionError("Action count changed")

        for i, (o, n) in enumerate(zip(original_sig, new_sig)):
            if o != n:
                raise AssertionError(
                    f"Action type changed at position {i}: {o} → {n}"
                )

    # ==================================================
    # STRUCTURE PRESERVATION (NOT STRING MATCH)
    # ==================================================

    def _preserves_structure(self, original: str, candidate: str) -> bool:
        """
        Allows locator repairs and API fixes
        but forbids reordering, removing, or changing action types.
        """
        return self._semantic_signature(original) == self._semantic_signature(candidate)

    # ==================================================
    # LLM COMPLETION (SAFETY ONLY)
    # ==================================================

    async def _run_llm_completion(
        self,
        *,
        intent: str,
        original_code: str,
        matched_script: Optional[str],
        reason: Optional[str],
        verification_mode: Optional[str],
    ) -> Optional[str]:

        prompt = self.template_engine.render(
            "step_safety_repair",
            intent=intent,
            original_code=original_code,
            reason=reason,
        )

        for attempt in range(LLM_MAX_RETRIES):
            try:
                result = await asyncio.wait_for(
                    self.llm.run(prompt, purpose="step_safety_repair"),
                    timeout=LLM_TIMEOUT_SEC,
                )
                if isinstance(result, str) and result.strip():
                    return result.strip()
            except Exception:
                await asyncio.sleep(LLM_BACKOFF_BASE * (2 ** attempt))

        return None

    # ==================================================
    # SANITIZATION
    # ==================================================

    _CODE_FENCE = re.compile(r"^\s*(`{3,}|~{3,})\w*\s*$")

    def _sanitize_llm_output(self, text: str) -> Optional[str]:
        lines = []
        for line in text.splitlines():
            if self._CODE_FENCE.match(line):
                continue
            if any(re.search(p, line) for p in self._FORBIDDEN_PATTERNS):
                continue
            if "await page.click(" in line or "await page.fill(" in line:
                continue
            if ":focus" in line:
                continue
            if "keyboard.type" in line:
                continue
            if "page.keyboard" in line:
                continue
            if ".press(" in line:
                continue

            lines.append(line.rstrip())

        return "\n".join(lines).strip() or None

    # ==================================================
    # SAFETY
    # ==================================================

    def _assert_no_forbidden_input_mechanics(self, code: str) -> None:
        forbidden = [
            ":focus",
            "keyboard.type",
            ".press(",
            "page.keyboard",
        ]

        for pattern in forbidden:
            if pattern in code:
                raise AssertionError(
                    f"Unsafe input pattern detected: '{pattern}'. "
                    "Only explicit locator-based input is allowed."
                )
