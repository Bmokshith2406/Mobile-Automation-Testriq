# app/services/classifier.py
"""
Action Classifier Service

Wraps the LLM classifier with additional retry logic.
"""

from typing import Optional
import logging

from app.models.cir import ActionType
from app.services.build_helpers.llm_classifier import LLMActionClassifier
from app.core.config import get_settings

logger = logging.getLogger("action_classifier")
settings = get_settings()


class ClassificationError(Exception):
    """Raised when classification fails."""
    pass


class ActionClassifier:
    """
    Pure LLM-based action classifier with confidence gating.
    
    Uses centralized configuration for all thresholds.
    """
    
    def __init__(self):
        self.llm = LLMActionClassifier()
        self.min_confidence = settings.MIN_CONFIDENCE_THRESHOLD
        self.max_retries = settings.MAX_EXTRACTOR_RETRIES
    
    async def classify(
        self,
        intent: str,
        expected_outcome: Optional[str],
        matched_script: Optional[str] = None,
    ) -> ActionType:

        if not intent or not intent.strip():
            logger.info("Empty intent → defaulting to assert_action")
            return ActionType.assert_action

        intent_l = intent.lower()

        if matched_script:
            ms_lower = matched_script.lower()
            if "goto(" in ms_lower or "go_back(" in ms_lower or "go_forward(" in ms_lower or "driver.get(" in ms_lower or "driver.back(" in ms_lower or "driver.forward(" in ms_lower:
                logger.info("Deterministic match from script → ActionType.navigate")
                return ActionType.navigate
            if "click(" in ms_lower or ".click()" in ms_lower:
                logger.info("Deterministic match from script → ActionType.click")
                return ActionType.click
            if "select_option(" in ms_lower or "select_by_" in ms_lower:
                logger.info("Deterministic match from script → ActionType.select")
                return ActionType.select
            if "fill(" in ms_lower or "send_keys(" in ms_lower:
                if any(k in intent_l for k in ("clear", "erase", "empty", "reset", "remove text")):
                    logger.info("Deterministic match from script + intent → ActionType.clear")
                    return ActionType.clear
                logger.info("Deterministic match from script → ActionType.type")
                return ActionType.type
            if "clear(" in ms_lower or ".clear()" in ms_lower:
                logger.info("Deterministic match from script → ActionType.clear")
                return ActionType.clear
            if "wait_for_selector(" in ms_lower or "expect(" in ms_lower or "assert" in ms_lower:
                logger.info("Deterministic match from script → ActionType.assert_action")
                return ActionType.assert_action
            if "drag_and_drop(" in ms_lower or "drag_to(" in ms_lower:
                return ActionType.drag_drop
            if "hover(" in ms_lower or "mouse_move(" in ms_lower:
                return ActionType.hover
            if "set_input_files(" in ms_lower or "upload_file(" in ms_lower:
                return ActionType.upload_file
            if "keyboard.press(" in ms_lower or ("press_keycode(" in ms_lower and "66" not in matched_script):
                return ActionType.keyboard
            if "switch_to.frame(" in ms_lower or "frame_locator(" in ms_lower:
                return ActionType.switch_frame
            if "switch_to.window(" in ms_lower or "switch_to_window(" in ms_lower:
                return ActionType.switch_window
            if "evaluate(" in ms_lower or "execute_script(" in ms_lower:
                return ActionType.execute_script
            if "dblclick(" in ms_lower or "double_click(" in ms_lower:
                return ActionType.double_click
            if "context_menu(" in ms_lower or "right_click(" in ms_lower or "button='right'" in ms_lower:
                return ActionType.right_click
            if "scroll_into_view" in ms_lower or "mouse.wheel(" in ms_lower or "scroll_down" in ms_lower:
                return ActionType.scroll

        if any(k in intent_l for k in ("clear", "erase", "empty", "reset", "remove text")):
            logger.info("Heuristic match → ActionType.clear")
            return ActionType.clear

        if any(k in intent_l for k in ("hover over", "mouse over", "hover on")):
            return ActionType.hover
        if any(k in intent_l for k in ("double click", "double-click", "dbl click")):
            return ActionType.double_click
        if any(k in intent_l for k in ("right click", "right-click", "context menu")):
            return ActionType.right_click
        if any(k in intent_l for k in ("drag", "drag and drop", "drag to")):
            return ActionType.drag_drop
        if any(k in intent_l for k in ("upload file", "attach file", "select file")):
            return ActionType.upload_file
        if any(k in intent_l for k in ("press tab", "press escape", "press ctrl", "press key")):
            return ActionType.keyboard
        if any(k in intent_l for k in ("switch to frame", "switch frame", "enter iframe")):
            return ActionType.switch_frame
        if any(k in intent_l for k in ("switch window", "switch tab", "new tab")):
            return ActionType.switch_window
        if any(k in intent_l for k in ("run script", "execute javascript", "execute script")):
            return ActionType.execute_script
        if any(k in intent_l for k in ("scroll down", "scroll up", "scroll to", "scroll into")):
            return ActionType.scroll

        last_result = None

        for attempt in range(self.max_retries + 1):
            try:
                # First attempt can use cache, retries must be fresh
                use_cache = attempt == 0

                result, confidence = await self.llm.classify_with_confidence(
                    intent=intent,
                    expected_outcome=expected_outcome,
                    matched_script=matched_script,
                    use_cache=use_cache,
                )

            except Exception as exc:
                logger.error("Classifier error | attempt=%d | error=%s", attempt, exc)
                continue

            last_result = result

            logger.info(
                "Classifier output | intent=%r | attempt=%d | result=%r | confidence=%r",
                intent,
                attempt,
                result,
                confidence,
            )


            if confidence is None:
                logger.debug("Confidence missing, retrying | attempt=%d", attempt)
                continue

            if confidence < self.min_confidence:
                logger.debug(
                    "Low confidence %f < %f, retrying | attempt=%d",
                    confidence,
                    self.min_confidence,
                    attempt,
                )
                continue

            if not isinstance(result, ActionType):
                logger.error("Invalid classifier output type | result=%r", result)
                continue

            logger.info(
                "Classifier accepted | intent=%r | result=%s | confidence=%r",
                intent,
                result,
                confidence,
            )

            return result

        logger.warning(
            "Classification failed | using heuristic fallback | last=%r | intent=%r",
            last_result,
            intent,
        )

        # Fallbacks
        if any(k in intent_l for k in ("type", "enter", "fill", "input")):
            logger.info("Fallback heuristic → ActionType.type")
            return ActionType.type

        if any(k in intent_l for k in ("click", "press", "tap", "submit")):
            logger.info("Fallback heuristic → ActionType.click")
            return ActionType.click

        if any(k in intent_l for k in ("select", "choose", "pick")):
            logger.info("Fallback heuristic → ActionType.select")
            return ActionType.select

        if any(k in intent_l for k in ("go to", "navigate", "open", "visit")):
            logger.info("Fallback heuristic → ActionType.navigate")
            return ActionType.navigate

        if any(k in intent_l for k in ("hover", "mouse over")):
            return ActionType.hover
        if any(k in intent_l for k in ("double click", "dbl click")):
            return ActionType.double_click
        if any(k in intent_l for k in ("right click", "context menu")):
            return ActionType.right_click
        if any(k in intent_l for k in ("scroll",)):
            return ActionType.scroll
        if any(k in intent_l for k in ("drag",)):
            return ActionType.drag_drop
        if any(k in intent_l for k in ("upload", "attach file")):
            return ActionType.upload_file

        logger.info("Fallback default → ActionType.assert_action")
        return ActionType.assert_action



