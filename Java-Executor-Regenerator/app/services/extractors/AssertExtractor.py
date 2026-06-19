from typing import Optional
import re
import logging

from app.core.llm_executor import LLMExecutor
from app.models.extraction import ExtractedAssertion, ExtractedLocator
from app.models.cir import AssertionType, LocatorStrategy, StepWait
from app.core.dom_pruner import DomPruner
from app.core.prompts import build_assert_extractor_prompt
from app.services.extractors.BaseExtractor import BaseExtractor

logger = logging.getLogger("assert_extractor")


class AssertActionExtractor(BaseExtractor):
    """
    Assertion evidence extractor for STEP REPAIR.
    """

    async def extract(
        self,
        *,
        step_intent: str,
        original_code: str,
        error_message: str,
        dom_snapshot: Optional[str] = None,
        page_url: Optional[str] = None,
        error_image_bytes: Optional[bytes] = None,
        framework: str = "playwright",
    ) -> Optional[ExtractedAssertion]:

        logger.debug("ASSERT EXTRACT | intent=%r", step_intent)

        intent_text = step_intent.lower()

        # URL-based assertion (deterministic, non-LLM)
        if page_url and "url" in intent_text:
            fragment = self._url_fragment(page_url)
            if fragment:
                logger.debug(
                    "ASSERT EXTRACT | url fragment detected: %s",
                    fragment,
                )
                return ExtractedAssertion(
                    type=AssertionType.url_contains,
                    expected=fragment,
                    locator=None,
                    wait=StepWait(),
                )

        self._last_step_intent = step_intent or ""
        self._last_original_code = original_code or ""
        self._last_dom_snapshot = dom_snapshot or ""

        llm_hint = await self._ask_llm(
            step_intent=step_intent,
            original_code=original_code,
            error_message=error_message,
            dom_snapshot=dom_snapshot,
            error_image_bytes=error_image_bytes,
            framework=framework,
        )

        if not llm_hint:
            logger.debug("ASSERT EXTRACT | LLM returned none")
            return None

        assertion = self._normalize_llm_hint(llm_hint, framework=framework)

        if not assertion:
            logger.warning(
                "ASSERT EXTRACT | discarded LLM hint: %r",
                llm_hint,
            )

        return assertion

    async def _ask_llm(
        self,
        *,
        step_intent: str,
        original_code: str,
        error_message: str,
        dom_snapshot: Optional[str],
        error_image_bytes: Optional[bytes],
        framework: str,
    ) -> Optional[str]:

        keyword = self._extract_quoted(step_intent)
        if not keyword:
            keyword = self._extract_quoted(original_code)

        pruned_dom = DomPruner.prune(dom_snapshot, keyword, framework=framework)
        self._last_dom_snapshot = pruned_dom or ""

        prompt = build_assert_extractor_prompt(
            step_intent=step_intent,
            original_code=original_code,
            error_message=error_message,
            dom_snapshot=pruned_dom,
            framework=framework,
        )

        executor = LLMExecutor.get_instance()

        if error_image_bytes:
            return await executor.run_multimodal_extractor(
                prompt=prompt,
                image_bytes=error_image_bytes,
            )

        return await executor.run_extractor(prompt)

    def _normalize_llm_hint(
        self,
        text: str,
        framework: str = "playwright",
    ) -> Optional[ExtractedAssertion]:

        raw = text.strip()
        lowered = raw.lower()

        if lowered == "none":
            return None

        if lowered.startswith("url_contains:"):
            value = raw.split(":", 1)[1].strip()
            if not value:
                return None

            return ExtractedAssertion(
                type=AssertionType.url_contains,
                expected=value,
                locator=None,
                wait=StepWait(),
            )

        if lowered == "element_visible":
            return ExtractedAssertion(
                type=AssertionType.element_is_visible,
                expected=None,
                locator=None,
                wait=StepWait(),
            )

        # ----------------------------------------------------------
        # Title-level assertions (no locator needed)
        # ----------------------------------------------------------
        if lowered.startswith("title_equals:"):
            value = raw.split(":", 1)[1].strip()
            if not value:
                return None
            return ExtractedAssertion(
                type=AssertionType.title_equals,
                expected=value,
                locator=None,
                wait=StepWait(),
            )

        if lowered.startswith("title_contains:"):
            value = raw.split(":", 1)[1].strip()
            if not value:
                return None
            return ExtractedAssertion(
                type=AssertionType.title_contains,
                expected=value,
                locator=None,
                wait=StepWait(),
            )

        if lowered.startswith("page_source_contains:"):
            value = raw.split(":", 1)[1].strip()
            if not value:
                return None
            return ExtractedAssertion(
                type=AssertionType.page_source_contains,
                expected=value,
                locator=None,
                wait=StepWait(),
            )

        # ----------------------------------------------------------
        # text_equals / text_contains (with optional locator hint)
        # Format: text_equals:<expected>[:<locator_hint>]
        # ----------------------------------------------------------
        for assert_type_key, assert_type_val in (
            ("text_equals:", AssertionType.text_equals),
            ("text_contains:", AssertionType.text_contains),
        ):
            if lowered.startswith(assert_type_key):
                remainder = raw[len(assert_type_key):].strip()
                parts = remainder.split(":", 1)
                expected = parts[0].strip()
                locator_hint = parts[1].strip() if len(parts) > 1 else None
                locator = None
                if locator_hint:
                    locator = ExtractedLocator(
                        strategy=LocatorStrategy.css,
                        value=locator_hint,
                    )
                return ExtractedAssertion(
                    type=assert_type_val,
                    expected=expected or None,
                    locator=locator,
                    wait=StepWait(),
                )

        # ----------------------------------------------------------
        # element_enabled / element_disabled / element_checked / element_unchecked
        # Format: element_enabled:<locator_hint>  (no expected value)
        # ----------------------------------------------------------
        for assert_type_key, assert_type_val in (
            ("element_enabled:", AssertionType.element_enabled),
            ("element_disabled:", AssertionType.element_disabled),
            ("element_checked:", AssertionType.element_checked),
            ("element_unchecked:", AssertionType.element_unchecked),
        ):
            if lowered.startswith(assert_type_key):
                locator_hint = raw[len(assert_type_key):].strip()
                locator = ExtractedLocator(
                    strategy=LocatorStrategy.css,
                    value=locator_hint,
                ) if locator_hint else None
                return ExtractedAssertion(
                    type=assert_type_val,
                    expected=None,
                    locator=locator,
                    wait=StepWait(),
                )

        # exact marker (no colon suffix)
        for assert_type_key, assert_type_val in (
            ("element_enabled", AssertionType.element_enabled),
            ("element_disabled", AssertionType.element_disabled),
            ("element_checked", AssertionType.element_checked),
            ("element_unchecked", AssertionType.element_unchecked),
        ):
            if lowered == assert_type_key:
                return ExtractedAssertion(
                    type=assert_type_val,
                    expected=None,
                    locator=None,
                    wait=StepWait(),
                )

        # ----------------------------------------------------------
        # element_value / list_contains / attribute_equals / attribute_contains
        # Format: <type>:<expected_value>:<locator_hint>
        # ----------------------------------------------------------
        for assert_type_key, assert_type_val in (
            ("element_value:", AssertionType.element_value),
            ("list_contains:", AssertionType.list_contains),
            ("attribute_equals:", AssertionType.attribute_equals),
            ("attribute_contains:", AssertionType.attribute_contains),
        ):
            if lowered.startswith(assert_type_key):
                remainder = raw[len(assert_type_key):].strip()
                parts = remainder.split(":", 1)
                expected = parts[0].strip()
                locator_hint = parts[1].strip() if len(parts) > 1 else None
                locator = ExtractedLocator(
                    strategy=LocatorStrategy.css,
                    value=locator_hint,
                ) if locator_hint else None
                return ExtractedAssertion(
                    type=assert_type_val,
                    expected=expected or None,
                    locator=locator,
                    wait=StepWait(),
                )

        # ----------------------------------------------------------
        # element_count:<expected_count>:<locator_hint>
        # ----------------------------------------------------------
        if lowered.startswith("element_count:"):
            remainder = raw[len("element_count:"):].strip()
            parts = remainder.split(":", 1)
            expected = parts[0].strip()
            locator_hint = parts[1].strip() if len(parts) > 1 else None
            locator = ExtractedLocator(
                strategy=LocatorStrategy.css,
                value=locator_hint,
            ) if locator_hint else None
            return ExtractedAssertion(
                type=AssertionType.element_count,
                expected=expected or None,
                locator=locator,
                wait=StepWait(),
            )

        if lowered.startswith("element_visible:"):
            hint_raw = raw.split(":", 1)[1].strip()
            hint_lower = hint_raw.lower()

            if (framework or "").strip().lower() == "appium":
                locator = self._appium_locator_from_hint(hint_raw)
                if not locator:
                    return None
                return ExtractedAssertion(
                    type=AssertionType.element_is_visible,
                    expected=None,
                    locator=locator,
                    wait=StepWait(),
                )

            # role(role_name, name="accessible name")
            if hint_lower.startswith("role("):
                m_role = re.match(r'^role\(\s*["\']([^"\']+)["\']\s*,\s*name\s*=\s*["\']([^"\']+)["\']\s*\)', hint_raw, re.IGNORECASE)
                if m_role:
                    role_type = m_role.group(1)
                    name_val = m_role.group(2)
                    if not self._literal_exists_in_sources(name_val):
                        logger.warning("ASSERT EXTRACT | rejected role name literal: %r", name_val)
                        return None
                    return ExtractedAssertion(
                        type=AssertionType.element_is_visible,
                        expected=None,
                        locator=ExtractedLocator(
                            strategy=LocatorStrategy.role,
                            value=f'"{role_type}", name="{name_val}"',
                        ),
                        wait=StepWait(),
                    )

            # placeholder("...")
            if hint_lower.startswith("placeholder("):
                m_placeholder = re.match(r'^placeholder\(\s*["\']([^"\']+)["\']\s*\)', hint_raw, re.IGNORECASE)
                if m_placeholder:
                    val = m_placeholder.group(1)
                    if not self._literal_exists_in_sources(val):
                        logger.warning("ASSERT EXTRACT | rejected placeholder literal: %r", val)
                        return None
                    return ExtractedAssertion(
                        type=AssertionType.element_is_visible,
                        expected=None,
                        locator=ExtractedLocator(
                            strategy=LocatorStrategy.placeholder,
                            value=val,
                        ),
                        wait=StepWait(),
                    )

            # label("...")
            if hint_lower.startswith("label("):
                m_label = re.match(r'^label\(\s*["\']([^"\']+)["\']\s*\)', hint_raw, re.IGNORECASE)
                if m_label:
                    val = m_label.group(1)
                    if not self._literal_exists_in_sources(val):
                        logger.warning("ASSERT EXTRACT | rejected label literal: %r", val)
                        return None
                    return ExtractedAssertion(
                        type=AssertionType.element_is_visible,
                        expected=None,
                        locator=ExtractedLocator(
                            strategy=LocatorStrategy.label,
                            value=val,
                        ),
                        wait=StepWait(),
                    )

            # css("...")
            if hint_lower.startswith("css("):
                m_css = re.match(r'^css\(\s*["\']([^"\']+)["\']\s*\)', hint_raw, re.IGNORECASE)
                if m_css:
                    val = m_css.group(1)
                    return ExtractedAssertion(
                        type=AssertionType.element_is_visible,
                        expected=None,
                        locator=ExtractedLocator(
                            strategy=LocatorStrategy.css,
                            value=val,
                        ),
                        wait=StepWait(),
                    )

            # xpath("...")
            if hint_lower.startswith("xpath("):
                m_xpath = re.match(r'^xpath\(\s*["\']([^"\']+)["\']\s*\)', hint_raw, re.IGNORECASE)
                if m_xpath:
                    val = m_xpath.group(1)
                    return ExtractedAssertion(
                        type=AssertionType.element_is_visible,
                        expected=None,
                        locator=ExtractedLocator(
                            strategy=LocatorStrategy.xpath,
                            value=val,
                        ),
                        wait=StepWait(),
                    )

            # test_id("...")
            if hint_lower.startswith("test_id("):
                m_testid = re.match(r'^test_id\(\s*["\']([^"\']+)["\']\s*\)', hint_raw, re.IGNORECASE)
                if m_testid:
                    val = m_testid.group(1)
                    if not self._literal_exists_in_sources(val):
                        logger.warning("ASSERT EXTRACT | rejected test_id literal: %r", val)
                        return None
                    return ExtractedAssertion(
                        type=AssertionType.element_is_visible,
                        expected=None,
                        locator=ExtractedLocator(
                            strategy=LocatorStrategy.test_id,
                            value=val,
                        ),
                        wait=StepWait(),
                    )

            # fallback: text("...") or just raw quoted string
            val = None
            if hint_lower.startswith("text("):
                val = self._extract_quoted(hint_raw)
            else:
                val = self._extract_quoted(raw)

            if val:
                if not self._literal_exists_in_sources(val):
                    logger.warning(
                        "ASSERT EXTRACT | rejected invented text literal: %r",
                        val,
                    )
                    return None

                return ExtractedAssertion(
                    type=AssertionType.element_is_visible,
                    expected=None,
                    locator=ExtractedLocator(
                        strategy=LocatorStrategy.text,
                        value=val,
                    ),
                    wait=StepWait(),
                )

        return None

    def _url_fragment(self, url: str) -> Optional[str]:
        try:
            path = re.sub(r"https?://[^/]+", "", url)
            segments = path.split("?", 1)[0].strip("/").split("/")
            return segments[-1] if segments and segments[-1] else None
        except Exception:
            return None
