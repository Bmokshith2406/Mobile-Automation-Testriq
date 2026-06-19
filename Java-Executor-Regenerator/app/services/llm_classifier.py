# app/services/llm_classifier.py

from typing import Optional
import re

from app.core.llm_executor import LLMExecutor
from app.core.prompts import build_action_classifier_prompt
from app.models.cir import ActionType


class LLMActionClassifier:
    """
    Fully LLM-based action classifier.

    The LLM is the semantic authority, but we add
    deterministic safety guards to prevent false ASSERTS.

    Screenshot (if present) is used ONLY to detect
    runtime dialogs, popups, modals, or blocking overlays.
    """

    ALLOWED_LABELS = {
        "navigate": ActionType.navigate,
        "click": ActionType.click,
        "type": ActionType.type,
        "select": ActionType.select,
        "assert": ActionType.assert_action,

        # Runtime interruption
        "dialog": ActionType.handle_dialog,
        "popup": ActionType.handle_dialog,
        "modal": ActionType.handle_dialog,

        # Enhanced: 11 new action types
        "hover": ActionType.hover,
        "doubleclickl": ActionType.double_click,
        "doubleclick": ActionType.double_click,
        "double_click": ActionType.double_click,
        "dblclick": ActionType.double_click,
        "rightclick": ActionType.right_click,
        "right_click": ActionType.right_click,
        "scroll": ActionType.scroll,
        "drag": ActionType.drag_drop,
        "dragdrop": ActionType.drag_drop,
        "drag_drop": ActionType.drag_drop,
        "upload": ActionType.upload_file,
        "upload_file": ActionType.upload_file,
        "keyboard": ActionType.keyboard,
        "frame": ActionType.switch_frame,
        "switch_frame": ActionType.switch_frame,
        "window": ActionType.switch_window,
        "switch_window": ActionType.switch_window,
        "script": ActionType.execute_script,
        "execute_script": ActionType.execute_script,
        "wait": ActionType.wait_for,
        "wait_for": ActionType.wait_for,
    }

    ASSERT_PATTERNS = [
        r"\bverify\b",
        r"\bcheck\b",
        r"\bensure\b",
        r"\bconfirm\b",
        r"\bvalidate\b",
        r"\bassert\b",
        r"\bshould\b",
        r"\bmust\b",
        r"\bexpect\b",
    ]

    CLICK_PATTERNS = [
        r"\bclick\b",
        r"\bpress\b",
        r"\btap\b",
        r"\bsubmit\b",
        r"\bopen\b",
    ]

    TYPE_PATTERNS = [
        r"\btype\b",
        r"\benter\b",
        r"\bfill\b",
        r"\binput\b",
    ]

    SELECT_PATTERNS = [
        r"\bselect\b",
        r"\bchoose\b",
        r"\bpick\b",
    ]

    NAVIGATE_PATTERNS = [
        r"\bnavigate\b",
        r"\bgo to\b",
        r"\bopen url\b",
        r"\bvisit\b",
        r"\bload\b",
    ]

    DOUBLE_CLICK_PATTERNS = [
        r"\bdouble.click\b",
        r"\bdouble.tap\b",
        r"\bdblclick\b",
    ]

    RIGHT_CLICK_PATTERNS = [
        r"\bright.click\b",
        r"\bcontext.menu\b",
        r"\bright.tap\b",
    ]

    HOVER_PATTERNS = [
        r"\bhover\b",
        r"\bmouseover\b",
        r"\bmouse over\b",
    ]

    DRAG_DROP_PATTERNS = [
        r"\bdrag.drop\b",
        r"\bdrag and drop\b",
        r"\bdrag\b",
    ]

    KEYBOARD_PATTERNS = [
        r"\bpress key\b",
        r"\bkeyboard shortcut\b",
        r"\bkey combination\b",
        r"\bctrl\s*\+",
        r"\bcmd\s*\+",
        r"\balt\s*\+",
        r"\bshift\s*\+",
        r"\bhit key\b",
    ]

    UPLOAD_PATTERNS = [
        r"\bupload\b",
        r"\battach file\b",
        r"\bfile input\b",
        r"\bchoose file\b",
    ]

    SCROLL_PATTERNS = [
        r"\bscroll\b",
        r"\bswipe\b",
        r"\bmouse wheel\b",
    ]

    SWITCH_FRAME_PATTERNS = [
        r"\bswitch.*frame\b",
        r"\bswitch to frame\b",
        r"\biframe\b",
    ]

    SWITCH_WINDOW_PATTERNS = [
        r"\bswitch.*window\b",
        r"\bnew tab\b",
        r"\bswitch tab\b",
        r"\bswitch to window\b",
    ]

    EXECUTE_SCRIPT_PATTERNS = [
        r"\bexecute script\b",
        r"\brun javascript\b",
        r"\bexecute js\b",
        r"\beval\b",
    ]

    WAIT_FOR_PATTERNS = [
        r"\bwait for\b",
        r"\bwait until\b",
        r"\bwait.*appear\b",
        r"\bwait.*visible\b",
        r"\bwait.*load\b",
    ]

    def __init__(self):
        self.llm = LLMExecutor.get_instance()

    def _matches(self, patterns, text: str) -> bool:
        text = text.lower()
        return any(re.search(p, text) for p in patterns)

    def _looks_like_assert(self, intent: str) -> bool:
        return self._matches(self.ASSERT_PATTERNS, intent)

    async def classify(
        self,
        *,
        step_intent: str,
        original_code: str,
        error_type: Optional[str],
        error_image_bytes: Optional[bytes] = None,
    ) -> ActionType:
        """
        Classify the failed step into a SINGLE ActionType.
        """

        intent_lower = step_intent.lower().strip()

        # ---------------------------
        # HARD GUARDS (NO LLM)
        # Enhanced: specific patterns must come before generic ones
        # ---------------------------

        # These must precede CLICK_PATTERNS to avoid "double click" → click
        if self._matches(self.DOUBLE_CLICK_PATTERNS, intent_lower):
            return ActionType.double_click

        if self._matches(self.RIGHT_CLICK_PATTERNS, intent_lower):
            return ActionType.right_click

        if self._matches(self.DRAG_DROP_PATTERNS, intent_lower):
            return ActionType.drag_drop

        if self._matches(self.HOVER_PATTERNS, intent_lower):
            return ActionType.hover

        if self._matches(self.KEYBOARD_PATTERNS, intent_lower):
            return ActionType.keyboard

        if self._matches(self.UPLOAD_PATTERNS, intent_lower):
            return ActionType.upload_file

        if self._matches(self.EXECUTE_SCRIPT_PATTERNS, intent_lower):
            return ActionType.execute_script

        if self._matches(self.SWITCH_FRAME_PATTERNS, intent_lower):
            return ActionType.switch_frame

        if self._matches(self.SWITCH_WINDOW_PATTERNS, intent_lower):
            return ActionType.switch_window

        if self._matches(self.WAIT_FOR_PATTERNS, intent_lower):
            return ActionType.wait_for

        if self._matches(self.CLICK_PATTERNS, intent_lower):
            return ActionType.click

        if self._matches(self.TYPE_PATTERNS, intent_lower):
            return ActionType.type

        if self._matches(self.SELECT_PATTERNS, intent_lower):
            return ActionType.select

        if self._matches(self.SCROLL_PATTERNS, intent_lower):
            return ActionType.scroll

        if self._matches(self.NAVIGATE_PATTERNS, intent_lower):
            return ActionType.navigate

        if self._matches(self.ASSERT_PATTERNS, intent_lower):
            return ActionType.assert_action

        # ---------------------------
        # LLM FALLBACK (AMBIGUOUS)
        # ---------------------------

        prompt = build_action_classifier_prompt(
            step_intent=step_intent,
            original_code=original_code,
            error_type=error_type,
        )

        try:
            if error_image_bytes:
                result = await self.llm.run_multimodal_classifier(
                    prompt=prompt,
                    image_bytes=error_image_bytes,
                )
            else:
                result = await self.llm.run_classifier(prompt)

        except Exception:
            return ActionType.click  # SAFE DEFAULT

        if not result:
            return ActionType.click  # SAFE DEFAULT

        label = re.sub(
            r"[^a-z]",
            "",
            result.lower().strip().split()[0],
        )

        action = self.ALLOWED_LABELS.get(label, ActionType.click)

        # ---------------------------
        # ASSERT SAFETY DOWNGRADE
        # ---------------------------
        if action == ActionType.assert_action:
            if not self._looks_like_assert(step_intent):
                return ActionType.click

        return action
