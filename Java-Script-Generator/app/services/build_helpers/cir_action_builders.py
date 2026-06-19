from typing import Optional, List
import re
import logging
import asyncio
import inspect

from app.models.cir import (
    CIRAction,
    ActionType,
    NavigateType,
    CIRAssertion,
    CIRLocator,
    AssertionType,
    LocatorStrategy,
)
from app.models.matched_script import MatchedScript
from app.services.build_helpers.classifier import ActionClassifier
from app.services.build_helpers.type_extractor import TypeActionExtractor
from app.services.build_helpers.click_extractor import ClickActionExtractor
from app.services.build_helpers.select_extractor import SelectActionExtractor
from app.services.build_helpers.assert_extractor import AssertActionExtractor
from app.services.build_helpers.script_parser import ScriptParser
from app.utils.locator_utils import normalize_locator

logger = logging.getLogger("cir.action_builders")

LLM_MAX_RETRIES = 3
LLM_BACKOFF_BASE = 0.5  # seconds

NAV_BACK_PATTERN = re.compile(r"\b(go back|navigate back|previous|return)\b", re.IGNORECASE)
NAV_FORWARD_PATTERN = re.compile(r"\b(go forward|navigate forward|next)\b", re.IGNORECASE)
NAV_BACK_SCRIPT_PATTERN = re.compile(r"\b(?:driver|page)\.(?:back|go_back)\s*\(", re.IGNORECASE)
NAV_FORWARD_SCRIPT_PATTERN = re.compile(r"\b(?:driver|page)\.(?:forward|go_forward)\s*\(", re.IGNORECASE)
NAV_REFRESH_SCRIPT_PATTERN = re.compile(r"\b(?:driver|page)\.(?:refresh|reload)\s*\(", re.IGNORECASE)
KEYBOARD_ENTER_INTENT_PATTERN = re.compile(
    r"\b(?:press|tap|hit|submit|confirm)\s+(?:the\s+)?"
    r"(?:enter|return|search|done|go)(?:\s+key)?\b"
    r"|\b(?:keyboard|ime)\s+(?:enter|return|search|done|go)\b",
    re.IGNORECASE,
)
KEYBOARD_ENTER_SCRIPT_PATTERN = re.compile(
    r"press_keycode\s*\(\s*66\s*\)"
    r"|KEYCODE_ENTER"
    r"|Keys\.ENTER"
    r"|send_keys\s*\(\s*['\"](?:\\n|\\r|\\ue007)['\"]\s*\)"
    r"|perform_editor_action\s*\(\s*['\"](?:search|done|go|enter)['\"]\s*\)",
    re.IGNORECASE,
)


class CIRActionBuilder:
    """
    Builds individual CIRActions safely from test cases, leveraging LLM action classifiers and extractors.
    """

    def __init__(self):
        self.classifier = ActionClassifier()
        self.type_extractor = TypeActionExtractor()
        self.select_extractor = SelectActionExtractor()
        self.click_extractor = ClickActionExtractor()
        self.assert_extractor = AssertActionExtractor()

    async def build_action_safe(
        self,
        atomic_intent: str,
        expected: Optional[str],
        matched_script: Optional[MatchedScript],
    ) -> CIRAction:
        script_code = matched_script.raw_code if matched_script else None
        framework = matched_script.framework if matched_script else None

        effective_framework = self._effective_framework(framework)
        if self._is_appium_framework(effective_framework) and self._is_keyboard_enter_action(
            atomic_intent,
            script_code,
        ):
            logger.info("Deterministic Appium keyboard Enter action | intent=%s", atomic_intent)
            return CIRAction(
                action_type=ActionType.type,
                value="\n",
            )

        action_type = await self.classifier.classify(
            atomic_intent,
            expected,
            script_code,
        )

        if action_type == ActionType.navigate:
            return await self._build_navigate_action(atomic_intent, script_code)

        elif action_type == ActionType.click:
            return await self._safe_click_action(atomic_intent, script_code, framework)

        elif action_type == ActionType.select:
            return await self._safe_select_action(atomic_intent, script_code, framework)

        elif action_type == ActionType.type:
            return await self._safe_type_action(atomic_intent, script_code, framework)

        elif action_type == ActionType.clear:
            return await self._safe_clear_action(atomic_intent, script_code, framework)

        elif action_type == ActionType.assert_action:
            return await self._safe_assert_action(atomic_intent, expected, script_code, framework)

        elif action_type == ActionType.hover:
            return await self._safe_hover_action(atomic_intent, script_code, framework)
        elif action_type == ActionType.double_click:
            return await self._safe_double_click_action(atomic_intent, script_code, framework)
        elif action_type == ActionType.right_click:
            return await self._safe_right_click_action(atomic_intent, script_code, framework)
        elif action_type == ActionType.scroll:
            return await self._safe_scroll_action(atomic_intent, script_code, framework)
        elif action_type == ActionType.drag_drop:
            return await self._safe_drag_drop_action(atomic_intent, script_code, framework)
        elif action_type == ActionType.upload_file:
            return await self._safe_upload_action(atomic_intent, script_code, framework)
        elif action_type == ActionType.keyboard:
            return await self._safe_keyboard_action(atomic_intent, script_code, framework)
        elif action_type == ActionType.switch_frame:
            return CIRAction(action_type=ActionType.switch_frame, frame_locator=atomic_intent)
        elif action_type == ActionType.switch_window:
            return CIRAction(action_type=ActionType.switch_window, window_index=0)
        elif action_type == ActionType.execute_script:
            return CIRAction(action_type=ActionType.execute_script, script_expression=atomic_intent)

        else:
            raise RuntimeError(f"Unsupported action type: {action_type}")

    async def _safe_click_action(
        self,
        intent: str,
        script: Optional[str],
        framework: Optional[str],
    ) -> CIRAction:
        extracted = await self._retry_llm(
            self.click_extractor.extract_locator,
            intent,
            script,
        )

        locator = self._to_cir_locator(extracted, framework)

        if not locator:
            locator = self._fallback_locator_from_script(script, framework)
            if locator:
                logger.warning("CLICK fallback locator used | intent=%s", intent)

        if not locator:
            raise RuntimeError(f"CLICK action missing locator | intent={intent}")

        return CIRAction(
            action_type=ActionType.click,
            target=locator,
            wait=self.click_extractor.extract_wait(intent, script),
        )

    async def _safe_clear_action(
        self,
        intent: str,
        script: Optional[str],
        framework: Optional[str],
    ) -> CIRAction:
        extracted = await self._retry_llm(
            self.type_extractor.extract_locator,
            intent,
            script,
        )

        locator = self._to_cir_locator(extracted, framework)

        if not locator:
            locator = self._fallback_locator_from_script(script, framework)
            if locator:
                logger.warning("CLEAR fallback locator used | intent=%s", intent)

        if not locator:
            raise RuntimeError(f"CLEAR action missing locator | intent={intent}")

        return CIRAction(
            action_type=ActionType.clear,
            target=locator,
            wait=self.type_extractor.extract_wait(intent, script),
        )

    async def _safe_type_action(
        self,
        intent: str,
        script: Optional[str],
        framework: Optional[str],
    ) -> CIRAction:
        locator_task = self._retry_llm(
            self.type_extractor.extract_locator,
            intent,
            script,
        )
        value_task = self._retry_llm(
            self.type_extractor.extract_value,
            intent,
            script,
        )

        extracted_locator, extracted_value = await asyncio.gather(locator_task, value_task)

        locator = self._to_cir_locator(extracted_locator, framework)
        value = extracted_value.value if extracted_value else None

        if not locator:
            locator = self._fallback_locator_from_script(script, framework)
            if locator:
                logger.warning("TYPE fallback locator used | intent=%s", intent)

        # 🔒 HARD GUARD
        if value is None:
            raise RuntimeError(f"TYPE action missing value | intent={intent}")

        if not locator and not self._is_keyboard_enter_action(intent, script):
            raise RuntimeError(f"TYPE action missing locator | intent={intent}")

        return CIRAction(
            action_type=ActionType.type,
            target=locator,
            value=value,
            wait=self.type_extractor.extract_wait(intent, script),
        )

    async def _safe_select_action(
        self,
        intent: str,
        script: Optional[str],
        framework: Optional[str],
    ) -> CIRAction:
        locator_task = self._retry_llm(
            self.select_extractor.extract_locator,
            intent,
            script,
        )
        value_task = self._retry_llm(
            self.select_extractor.extract_value,
            intent,
            script,
        )

        extracted_locator, extracted_value = await asyncio.gather(locator_task, value_task)

        locator = self._to_cir_locator(extracted_locator, framework)
        value = extracted_value.value if extracted_value else None

        if not locator:
            locator = self._fallback_locator_from_script(script, framework)
            if locator:
                logger.warning("SELECT fallback locator used | intent=%s", intent)

        # 🔒 HARD CONTRACT
        if not locator:
            raise RuntimeError(f"SELECT action missing locator | intent={intent}")

        if value is None:
            raise RuntimeError(f"SELECT action missing value | intent={intent}")

        return CIRAction(
            action_type=ActionType.select,
            target=locator,
            value=value,
            value_mode=extracted_value.mode if extracted_value else None,
            wait=self.select_extractor.extract_wait(intent, script),
        )

    async def _safe_assert_action(
        self,
        intent: str,
        expected: Optional[str],
        script: Optional[str],
        framework: Optional[str],
    ) -> CIRAction:
        extracted = await self._retry_llm(
            self.assert_extractor.extract,
            intent,
            expected,
            script,
        )

        if not extracted:
            raise RuntimeError(f"ASSERT extraction failed | intent={intent}")

        target = self._to_cir_locator(extracted.locator, framework)
        atype = extracted.assert_type
        expected_value = extracted.expected_value

        # =====================================================
        # VISIBILITY ASSERTION
        # =====================================================
        if atype == AssertionType.element_is_visible:
            if not target:
                raise RuntimeError("element_is_visible requires target")
            if expected_value:
                raise RuntimeError("element_is_visible must NOT have expected_value")

        # =====================================================
        # TEXT ASSERTIONS
        # =====================================================
        if atype in {
            AssertionType.text_equals,
            AssertionType.text_contains,
        }:
            if expected_value is None:
                raise RuntimeError("Text assertion missing expected_value")
            if not target:
                raise RuntimeError(f"{atype} requires a target")

        # =====================================================
        # URL ASSERTION
        # =====================================================
        if atype == AssertionType.url_contains:
            if expected_value is None:
                raise RuntimeError("url_contains assertion missing expected_value")
            if target:
                raise RuntimeError("url_contains must NOT have a target")

        # =====================================================
        # TITLE ASSERTIONS
        # =====================================================
        if atype in {
            AssertionType.title_contains,
            AssertionType.title_equals,
        }:
            if expected_value is None:
                raise RuntimeError("title assertion missing expected_value")
            if target:
                raise RuntimeError("title assertions must NOT have a target")

        if atype == AssertionType.text_contains and expected:
            if expected.strip() == expected_value:
                logger.warning("Upgrading text_contains → text_equals | intent=%s", intent)
                atype = AssertionType.text_equals

        if atype == AssertionType.title_contains and expected:
            if expected.strip() == expected_value:
                logger.warning("Upgrading title_contains → title_equals | intent=%s", intent)
                atype = AssertionType.title_equals

        return CIRAction(
            action_type=ActionType.assert_action,
            target=target,
            assertion=CIRAssertion(
                assert_type=atype,
                expected_value=expected_value,
            ),
            wait=extracted.wait,
        )

    async def _build_navigate_action(
        self,
        intent: str,
        script: Optional[str],
    ) -> CIRAction:
        if script and NAV_BACK_SCRIPT_PATTERN.search(script):
            return CIRAction(
                action_type=ActionType.navigate,
                navigate_type=NavigateType.back,
            )

        if script and NAV_FORWARD_SCRIPT_PATTERN.search(script):
            return CIRAction(
                action_type=ActionType.navigate,
                navigate_type=NavigateType.forward,
            )

        if script and NAV_REFRESH_SCRIPT_PATTERN.search(script):
            return CIRAction(
                action_type=ActionType.navigate,
                navigate_type=NavigateType.refresh,
            )

        if NAV_BACK_PATTERN.search(intent):
            return CIRAction(
                action_type=ActionType.navigate,
                navigate_type=NavigateType.back,
            )

        if NAV_FORWARD_PATTERN.search(intent):
            return CIRAction(
                action_type=ActionType.navigate,
                navigate_type=NavigateType.forward,
            )

        url = None
        if script:
            m = re.search(r"https?://[^\s'\"`)]+", script)
            if m:
                url = m.group(0)

        if not url:
            m = re.search(r"https?://[^\s'\"`)]+", intent)
            if m:
                url = m.group(0)

        if url:
            return CIRAction(
                action_type=ActionType.navigate,
                navigate_type=NavigateType.url,
                value=url,
            )

        raise RuntimeError(
            f"Navigate intent but no URL/back/forward detected | intent={intent}"
        )

    async def _retry_llm(self, fn, *args):
        params = inspect.signature(fn).parameters
        for attempt in range(LLM_MAX_RETRIES):
            try:
                use_cache = attempt == 0
                if "use_cache" in params:
                    result = await fn(*args, use_cache=use_cache)
                elif "cache" in params:
                    result = await fn(*args, cache=use_cache)
                else:
                    result = await fn(*args)
                if result:
                    return result
            except Exception as e:
                logger.warning("LLM call failed | fn=%s | attempt=%s | error=%s", fn.__name__, attempt + 1, e)
            await asyncio.sleep(LLM_BACKOFF_BASE * (2 ** attempt))
        return None

    async def _safe_hover_action(self, intent: str, script: Optional[str], framework: Optional[str]) -> CIRAction:
        extracted = await self._retry_llm(self.click_extractor.extract_locator, intent, script)
        locator = self._to_cir_locator(extracted, framework)
        if not locator:
            locator = self._fallback_locator_from_script(script, framework)
        if not locator:
            raise RuntimeError(f"HOVER action missing locator | intent={intent}")
        return CIRAction(action_type=ActionType.hover, target=locator)

    async def _safe_double_click_action(self, intent: str, script: Optional[str], framework: Optional[str]) -> CIRAction:
        extracted = await self._retry_llm(self.click_extractor.extract_locator, intent, script)
        locator = self._to_cir_locator(extracted, framework)
        if not locator:
            locator = self._fallback_locator_from_script(script, framework)
        if not locator:
            raise RuntimeError(f"DOUBLE_CLICK action missing locator | intent={intent}")
        return CIRAction(action_type=ActionType.double_click, target=locator)

    async def _safe_right_click_action(self, intent: str, script: Optional[str], framework: Optional[str]) -> CIRAction:
        extracted = await self._retry_llm(self.click_extractor.extract_locator, intent, script)
        locator = self._to_cir_locator(extracted, framework)
        if not locator:
            locator = self._fallback_locator_from_script(script, framework)
        if not locator:
            raise RuntimeError(f"RIGHT_CLICK action missing locator | intent={intent}")
        return CIRAction(action_type=ActionType.right_click, target=locator)

    async def _safe_scroll_action(self, intent: str, script: Optional[str], framework: Optional[str]) -> CIRAction:
        extracted = await self._retry_llm(self.click_extractor.extract_locator, intent, script)
        locator = self._to_cir_locator(extracted, framework)
        direction = "down"
        if "up" in (intent or "").lower():
            direction = "up"
        elif "into view" in (intent or "").lower():
            direction = "into_view"
        return CIRAction(action_type=ActionType.scroll, target=locator, scroll_direction=direction)

    async def _safe_drag_drop_action(self, intent: str, script: Optional[str], framework: Optional[str]) -> CIRAction:
        extracted = await self._retry_llm(self.click_extractor.extract_locator, intent, script)
        locator = self._to_cir_locator(extracted, framework)
        if not locator:
            raise RuntimeError(f"DRAG_DROP action missing source locator | intent={intent}")
        return CIRAction(action_type=ActionType.drag_drop, target=locator, drag_target=locator)

    async def _safe_upload_action(self, intent: str, script: Optional[str], framework: Optional[str]) -> CIRAction:
        extracted = await self._retry_llm(self.click_extractor.extract_locator, intent, script)
        locator = self._to_cir_locator(extracted, framework)
        if not locator:
            raise RuntimeError(f"UPLOAD_FILE action missing locator | intent={intent}")
        import re
        path_match = re.search(r"['\"]([^'\"]+\.[a-zA-Z]{2,5})['\"]", script or "")
        file_path = path_match.group(1) if path_match else "/path/to/file"
        return CIRAction(action_type=ActionType.upload_file, target=locator, file_path_to_upload=file_path)

    async def _safe_keyboard_action(self, intent: str, script: Optional[str], framework: Optional[str]) -> CIRAction:
        import re
        key_match = re.search(r"(?:press|key)[:\s]+([A-Za-z0-9+\-]+)", intent or "", re.I)
        key = key_match.group(1) if key_match else "Tab"
        script_key_match = re.search(r"press\(['\"]([^'\"]+)['\"]\)", script or "")
        if script_key_match:
            key = script_key_match.group(1)
        return CIRAction(action_type=ActionType.keyboard, key_combination=key)

    def _to_cir_locator(
        self,
        extracted,
        framework: Optional[str] = None,
    ) -> Optional[CIRLocator]:
        if not extracted:
            return None

        if self._is_appium_framework(framework):
            return CIRLocator(
                locator_strategy=extracted.locator_strategy,
                locator_value=extracted.locator_value.strip(),
            )

        strategy, value = normalize_locator(
            extracted.locator_strategy,
            extracted.locator_value,
        )

        return CIRLocator(
            locator_strategy=strategy,
            locator_value=value,
        )

    def _fallback_locator_from_script(
        self,
        script: Optional[str],
        framework: Optional[str] = None,
    ) -> Optional[CIRLocator]:
        if not script:
            return None

        extracted = ScriptParser.extract_locator(script)
        if extracted:
            return self._to_cir_locator(extracted, framework)

        return None

    @staticmethod
    def _is_appium_framework(framework: Optional[str]) -> bool:
        return (framework or "").strip().lower() == "appium"

    @staticmethod
    def _effective_framework(framework: Optional[str]) -> Optional[str]:
        if framework:
            return framework

        try:
            from app.core.context import active_framework_ctx

            return active_framework_ctx.get(None)
        except Exception:
            return None

    @staticmethod
    def _is_keyboard_enter_action(intent: Optional[str], script: Optional[str]) -> bool:
        if script and KEYBOARD_ENTER_SCRIPT_PATTERN.search(script):
            return True

        if intent and KEYBOARD_ENTER_INTENT_PATTERN.search(intent):
            return True

        return False

