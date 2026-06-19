# app/services/step_modifier.py

import ast
from typing import Optional, List, Tuple, Dict, Any
import logging
import re

from app.core.llm_executor import LLMExecutor
from app.core.prompts import build_step_modifier_prompt

logger = logging.getLogger("step_modifier")


class StepModifier:
    """
    VERIFIER-DRIVEN STEP MODIFIER (MICRO-REPAIR)

    Guarantees:
    - Preserves step structure using semantic signature
    - Allows only expression-level edits
    - Never changes step count or order
    - NEVER modifies runtime fallback / dialog logic
    - Sandboxed against code injection
    """

    # --------------------------------------------------
    # HARD FORBIDDEN (STRUCTURAL / EXECUTION ESCAPES)
    # --------------------------------------------------
    _FORBIDDEN_PATTERNS = (
        r"\basync_playwright\b",
        r"\bbrowser\s*=",
        r"\bcontext\s*=",
        r"\bpage\s*=",
        r"\bpage\.goto\b",
        r"\bpage\.go_back\b",
        r"\bpage\.go_forward\b",
        r"\bpage\.evaluate\b",
        r"\bexec\b|\beval\b",
        r"__import__",
        r"\bopen\b|\blistdir\b",
        r"\blambda\b",
        r";",                      # multiple statements
        r"\\",                     # line continuation escape
        r"'''|\"\"\"",             # multiline strings
        r"^\s*import\s+",
        r"^\s*from\s+",
        r"\basync\s+def\b",
        r"^\s*def\b",
        r"^\s*class\b",
        r"\btry\s*:?|\bexcept\b|\bfinally\b",
        r"^\s*for\s+|\s+while\s+",
    )

    # Runtime / fallback logic — NEVER TOUCH
    _FALLBACK_PATTERNS = (
        r"\bpage\.once\(\s*['\"]dialog['\"]",
        r"\bd\.accept\(\)",
        r"\bd\.dismiss\(\)",
        r"\bhandle_dialog\b",
        r"\bcookie\b",
        r"\bpopup\b",
        r"\bmodal\b",
    )

    _STRATEGY_KEYWORDS = {
        "button", "link", "textbox", "checkbox", "combobox", "dialog", "heading",
        "img", "listbox", "menuitem", "option", "radio", "spinbutton", "tab",
        "tabpanel", "treeitem", "role", "text", "placeholder", "label", "css",
        "xpath", "id", "class", "name", "test_id", "domcontentloaded", "visible",
        "hidden", "attached", "detached", "timeout", "exact", "value"
    }

    def __init__(self, llm: Optional[LLMExecutor] = None):
        self.llm = llm or LLMExecutor.get_instance()
        logger.warning("StepModifier initialized | mode=verifier_driven")

    # ==================================================
    # PUBLIC ENTRY
    # ==================================================

    async def modify(
        self,
        *,
        intent: str,
        generated_code: str,
        verifier_reason: str,
        error_message: Optional[str] = None,
        failure_history: Optional[list[str]] = None,
        framework: str = "playwright",
    ) -> str:

        original = (generated_code or "").strip()
        if not original:
            return original

        # --------------------------------------------------
        # HARD GUARD: DO NOT MODIFY FALLBACK / DIALOG CODE
        # --------------------------------------------------
        if self._contains_fallback_logic(original):
            logger.info(
                "STEP MODIFIER SKIPPED | reason=runtime_fallback_code"
            )
            return original

        if not verifier_reason or not verifier_reason.strip():
            logger.info(
                "STEP MODIFIER SKIPPED | reason=missing_verifier_feedback"
            )
            return original

        prompt = self._build_prompt(
            intent=intent,
            code=original,
            verifier_reason=verifier_reason,
            error_message=error_message,
            failure_history=failure_history,
            framework=framework,
        )

        try:
            llm_output = await self.llm.run_modifier(prompt)
        except Exception:
            logger.exception("STEP MODIFIER | LLM call failed")
            return original

        if not llm_output or not isinstance(llm_output, str):
            logger.info(
                "STEP MODIFIER NO-OP | reason=empty_llm_output"
            )
            return original

        sanitized = self._sanitize_llm_output(llm_output, framework=framework)
        if not sanitized:
            logger.warning(
                "STEP MODIFIER REJECTED | reason=sanitization_failed"
            )
            return original

        if not self._is_structurally_equivalent(original, sanitized):
            logger.info(
                "STEP MODIFIER REJECTED | reason=structural_mismatch\n"
                "----- ORIGINAL STEP -----\n%s\n"
                "----- MODIFIED STEP -----\n%s\n"
                "-------------------------",
                original,
                sanitized,
            )
            return original

        # NEW: deterministic literal-preservation check
        ok, reason = self._runtime_literals_preserved(original, sanitized)
        if not ok:
            logger.info(
                "STEP MODIFIER REJECTED | reason=literal_preservation_failed | details=%s",
                reason,
            )
            return original

        if sanitized == original:
            logger.info(
                "STEP MODIFIER NO-OP | reason=identical_code"
            )
            return original

        logger.warning(
            "STEP MODIFIER APPLIED | source=verifier_guided_llm"
        )
        return sanitized

    # ==================================================
    # PROMPT
    # ==================================================

    def _build_prompt(
        self,
        *,
        intent: str,
        code: str,
        verifier_reason: str,
        error_message: Optional[str],
        failure_history: Optional[list[str]],
        framework: str = "playwright",
    ) -> str:
        return build_step_modifier_prompt(
            intent=intent,
            code=code,
            verifier_reason=verifier_reason,
            error_message=error_message or "N/A",
            failure_history=failure_history,
            framework=framework,
        )

    # ==================================================
    # SANITIZATION
    # ==================================================

    def _sanitize_llm_output(self, text: str, framework: str = "playwright") -> Optional[str]:
        lines = []

        for line in text.splitlines():
            stripped = line.rstrip()

            if any(
                re.search(pattern, stripped, re.IGNORECASE)
                for pattern in self._FORBIDDEN_PATTERNS
            ):
                return None

            lines.append(stripped)

        result = "\n".join(lines).strip()
        if not result:
            return None

        # AST Safety Check to strictly block execution escapes and structural changes
        if framework in ("playwright", "selenium", "appium"):
            try:
                nodes = self._parse_as_function_body_nodes(result)
                for node in nodes:
                    for child in ast.walk(node):
                        if isinstance(child, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.For, ast.While)):
                            logger.warning("AST safety violation: forbidden block %s", type(child).__name__)
                            return None
                        if type(child).__name__.startswith("Try"):
                            logger.warning("AST safety violation: forbidden try/except block")
                            return None
                        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id in ("eval", "exec", "__import__"):
                            logger.warning("AST safety violation: forbidden call to %s", child.func.id)
                            return None
            except Exception as exc:
                logger.warning("AST safety check failed to parse candidate: %s", exc)
                return None

        return result

    # ==================================================
    # SEMANTIC SIGNATURE & STRUCTURAL SAFETY
    # ==================================================

    def _semantic_signature(self, code: str) -> List[str]:
        sig = []
        for line in code.splitlines():
            l = line.strip()
            if not l or l.startswith("#"):
                continue

            # click/tap
            if any(pat in l for pat in [".click(", "click()", ".tap(", "tap("]):
                sig.append("click")
            # clear
            elif any(pat in l for pat in [".clear()", ".fill('')", '.fill("")', ".clear_text()"]):
                sig.append("clear")
            # type/fill/send_keys
            elif any(pat in l for pat in [".fill(", "send_keys(", "type(", ".type(", "set_value(", "set_text("]):
                sig.append("type")
            # select
            elif any(pat in l for pat in [".select_option", "select_by_", ".select(", "Select("]):
                sig.append("select")
            # navigate
            elif any(pat in l for pat in ["page.goto(", "go_back(", "go_forward(", "page.reload(", "driver.get(", "cy.visit(", "cy.go(", "navigate("]):
                sig.append("navigate")
            # assert
            elif any(pat in l for pat in ["to_have_text", "assert ", ".should(", "expect(", ".and("]):
                if "to_be_visible" in l or "is_displayed" in l:
                    pass
                else:
                    sig.append("assert")
        return sig

    def _is_structurally_equivalent(
        self,
        original: str,
        candidate: str,
    ) -> bool:
        return self._semantic_signature(original) == self._semantic_signature(candidate)

    # ==================================================
    # LITERAL PRESERVATION CHECK (DETERMINISTIC)
    # ==================================================

    def _collect_constants_from_code(self, code: str) -> List[Any]:
        try:
            wrapper = "async def _x():\n" + self._indent(code)
            tree = ast.parse(wrapper)
            consts = []
            for child in ast.walk(tree):
                if isinstance(child, ast.Constant) and isinstance(child.value, (str, int, float, bool)):
                    consts.append(child.value)
            return consts
        except Exception:
            # Fallback regex search if AST parsing fails (e.g. Cypress)
            strings = re.findall(r'["\'](.*?)["\']', code)
            numbers = [int(n) for n in re.findall(r'\b\d+\b', code)]
            return list(strings) + list(numbers)

    def _runtime_literals_preserved(self, original: str, candidate: str) -> Tuple[bool, str]:
        """
        Verify that user-defined literals (excluding selector/strategy keywords and timeouts)
        present in `original` are preserved in `candidate`.
        """
        orig_consts = self._collect_constants_from_code(original)
        cand_consts = self._collect_constants_from_code(candidate)

        def is_user_literal(val: Any) -> bool:
            if isinstance(val, str):
                return val.lower().strip() not in self._STRATEGY_KEYWORDS
            if isinstance(val, (int, float)):
                if val in {1000, 2000, 3000, 5000, 10000, 15000, 30000, 60000, 15, 30, 45, 60}:
                    return False
            return True

        orig_user_consts = [c for c in orig_consts if is_user_literal(c)]
        cand_user_consts = [c for c in cand_consts if is_user_literal(c)]

        for o_val in orig_user_consts:
            found = False
            for c_val in cand_user_consts:
                if isinstance(o_val, str) and isinstance(c_val, str):
                    if o_val.lower().strip() == c_val.lower().strip():
                        found = True
                        break
                else:
                    if o_val == c_val:
                        found = True
                        break
            if not found:
                # Check assignments in candidate
                try:
                    wrapper = "async def _x():\n" + self._indent(candidate)
                    tree = ast.parse(wrapper)
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Assign):
                            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                                val = node.value
                                if isinstance(val, ast.Constant) and isinstance(val.value, (str, int, float, bool)):
                                    if (isinstance(o_val, str) and isinstance(val.value, str) and o_val.lower().strip() == val.value.lower().strip()) or o_val == val.value:
                                        found = True
                                        break
                except Exception:
                    pass

            if not found:
                return False, f"literal_not_preserved: {o_val!r}"

        return True, "ok"

    def _parse_as_function_body_nodes(self, body_code: str) -> List[ast.stmt]:
        wrapper = "async def _x():\n" + self._indent(body_code)
        tree = ast.parse(wrapper)
        fn = tree.body[0]
        if not isinstance(fn, (ast.AsyncFunctionDef, ast.FunctionDef)):
            raise ValueError("wrapped node is not a function")
        return fn.body

    # ==================================================
    # FALLBACK DETECTION
    # ==================================================

    def _contains_fallback_logic(self, code: str) -> bool:
        for pattern in self._FALLBACK_PATTERNS:
            if re.search(pattern, code, re.IGNORECASE):
                return True
        return False

    def _indent(self, code: str) -> str:
        return "\n".join("    " + l if l.strip() else l for l in code.splitlines())
