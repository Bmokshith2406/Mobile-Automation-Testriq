from typing import Optional, Tuple
import logging
import re

from app.core.llm_executor import LLMExecutor
from app.models.extraction import ExtractedLocator, ExtractedValue
from app.models.cir import LocatorStrategy
from app.core.dom_pruner import DomPruner
from app.core.prompts import build_select_extractor_prompt
from app.services.extractors.BaseExtractor import BaseExtractor

logger = logging.getLogger("select_extractor")


class SelectActionExtractor(BaseExtractor):
    """
    SELECT action evidence extractor for STEP REPAIR.
    """

    async def extract(
        self,
        *,
        step_intent: str,
        original_code: str,
        error_message: str,
        dom_snapshot: Optional[str],
        page_url: Optional[str],
        error_image_bytes: Optional[bytes] = None,
        framework: str = "playwright",
    ) -> Tuple[Optional[ExtractedLocator], Optional[ExtractedValue]]:

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
            return None, None

        result = self._normalize_llm_hint(llm_hint, framework=framework)

        if result == (None, None):
            logger.warning(
                "SELECT EXTRACT | rejected LLM hint: %r",
                llm_hint,
            )

        return result

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

        prompt = build_select_extractor_prompt(
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
    ) -> Tuple[Optional[ExtractedLocator], Optional[ExtractedValue]]:

        if not isinstance(text, str):
            return None, None

        raw = text.strip()
        lowered = raw.lower()

        if lowered == "none":
            return None, None

        if not lowered.startswith("select:"):
            return None, None

        value_part_match = re.search(r'value\s*\(\s*(["\']).*?\1\s*\)', raw, flags=re.DOTALL)
        if not value_part_match:
            loose = re.search(r'value\(["\']?(.*?)["\']?\)', raw)
            if not loose:
                return None, None
            option_text = loose.group(1)
        else:
            idx = raw.lower().rfind("value(")
            option_text = self._extract_quoted(raw[idx:])
            if option_text is None:
                m = re.search(r'value\(\s*["\'](.*?)["\']\s*\)', raw)
                if not m:
                    return None, None
                option_text = m.group(1)

        if option_text is None:
            return None, None

        if not self._literal_exists_in_sources(option_text):
            logger.warning(
                "SELECT EXTRACT | rejected invented option literal: %r",
                option_text,
            )
            return None, None

        value = ExtractedValue(value=option_text)

        parts = raw.rsplit("value(", 1)
        if not parts:
            return None, None
        locator_part = parts[0].strip()

        loc_part_lower = locator_part.lower()

        if (framework or "").strip().lower() == "appium":
            locator_hint = locator_part.split(":", 1)[1].strip()
            locator = self._appium_locator_from_hint(locator_hint)
            return (locator, value) if locator else (None, None)

        # role(role_name, name="accessible name")
        if loc_part_lower.startswith("select:role("):
            m_role = re.match(r'^select:role\(\s*["\']([^"\']+)["\']\s*,\s*name\s*=\s*["\']([^"\']+)["\']\s*\)', locator_part, re.IGNORECASE)
            if m_role:
                role_type = m_role.group(1)
                name_val = m_role.group(2)
                if not self._literal_exists_in_sources(name_val):
                    logger.warning("SELECT EXTRACT | rejected role name literal: %r", name_val)
                    return None, None
                locator = ExtractedLocator(
                    strategy=LocatorStrategy.role,
                    value=f'"{role_type}", name="{name_val}"',
                )
                return locator, value

        # placeholder("...")
        if loc_part_lower.startswith("select:placeholder("):
            m_placeholder = re.match(r'^select:placeholder\(\s*["\']([^"\']+)["\']\s*\)', locator_part, re.IGNORECASE)
            if m_placeholder:
                val = m_placeholder.group(1)
                if not self._literal_exists_in_sources(val):
                    logger.warning("SELECT EXTRACT | rejected placeholder literal: %r", val)
                    return None, None
                locator = ExtractedLocator(
                    strategy=LocatorStrategy.placeholder,
                    value=val,
                )
                return locator, value

        # label("...")
        if loc_part_lower.startswith("select:label("):
            m_label = re.match(r'^select:label\(\s*["\']([^"\']+)["\']\s*\)', locator_part, re.IGNORECASE)
            if m_label:
                val = m_label.group(1)
                if not self._literal_exists_in_sources(val):
                    logger.warning("SELECT EXTRACT | rejected label literal: %r", val)
                    return None, None
                locator = ExtractedLocator(
                    strategy=LocatorStrategy.label,
                    value=val,
                )
                return locator, value

        # css("...")
        if loc_part_lower.startswith("select:css("):
            m_css = re.match(r'^select:css\(\s*["\']([^"\']+)["\']\s*\)', locator_part, re.IGNORECASE)
            if m_css:
                val = m_css.group(1)
                locator = ExtractedLocator(
                    strategy=LocatorStrategy.css,
                    value=val,
                )
                return locator, value

        # xpath("...")
        if loc_part_lower.startswith("select:xpath("):
            m_xpath = re.match(r'^select:xpath\(\s*["\']([^"\']+)["\']\s*\)', locator_part, re.IGNORECASE)
            if m_xpath:
                val = m_xpath.group(1)
                locator = ExtractedLocator(
                    strategy=LocatorStrategy.xpath,
                    value=val,
                )
                return locator, value

        # test_id("...")
        if loc_part_lower.startswith("select:test_id("):
            m_testid = re.match(r'^select:test_id\(\s*["\']([^"\']+)["\']\s*\)', locator_part, re.IGNORECASE)
            if m_testid:
                val = m_testid.group(1)
                if not self._literal_exists_in_sources(val):
                    logger.warning("SELECT EXTRACT | rejected test_id literal: %r", val)
                    return None, None
                locator = ExtractedLocator(
                    strategy=LocatorStrategy.test_id,
                    value=val,
                )
                return locator, value

        # text("...") fallback
        if loc_part_lower.startswith("select:text("):
            loc_text = self._extract_quoted(locator_part)
            if loc_text:
                if not self._literal_exists_in_sources(loc_text):
                    logger.warning(
                        "SELECT EXTRACT | rejected invented dropdown literal: %r",
                        loc_text,
                    )
                    return None, None

                locator = ExtractedLocator(
                    strategy=LocatorStrategy.text,
                    value=loc_text,
                )
                return locator, value

        logger.warning(
            "SELECT EXTRACT | unsupported locator grammar: %s",
            locator_part,
        )
        return None, None
