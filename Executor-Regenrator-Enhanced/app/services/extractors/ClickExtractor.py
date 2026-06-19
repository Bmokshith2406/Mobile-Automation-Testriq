from typing import Optional
import logging

from app.core.llm_executor import LLMExecutor
from app.models.extraction import ExtractedLocator
from app.models.cir import LocatorStrategy
from app.core.dom_pruner import DomPruner
from app.core.prompts import build_click_extractor_prompt
from app.services.extractors.BaseExtractor import BaseExtractor

logger = logging.getLogger("click_extractor")


class ClickActionExtractor(BaseExtractor):
    """
    CLICK locator evidence extractor for STEP REPAIR.
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
    ) -> Optional[ExtractedLocator]:

        logger.info(
            "CLICK EXTRACT | intent=%r | error=%r",
            step_intent,
            error_message,
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
            logger.debug("CLICK EXTRACT | LLM returned none")
            return None

        locator = self._normalize_llm_hint(llm_hint, framework=framework)

        if not locator:
            logger.warning(
                "CLICK EXTRACT | discarded LLM hint: %r",
                llm_hint,
            )

        return locator

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

        prompt = build_click_extractor_prompt(
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
    ) -> Optional[ExtractedLocator]:

        if not isinstance(text, str):
            return None

        raw = text.strip()
        lowered = raw.lower()

        if lowered == "none":
            return None

        if not lowered.startswith("click:"):
            return None

        hint_raw = raw.split(":", 1)[1].strip()
        hint_lower = hint_raw.lower()

        import re

        if (framework or "").strip().lower() == "appium":
            return self._appium_locator_from_hint(hint_raw)

        # role(role_name, name="accessible name")
        m_role = re.match(r'^role\(\s*["\']([^"\']+)["\']\s*,\s*name\s*=\s*["\']([^"\']+)["\']\s*\)', hint_raw, re.IGNORECASE)
        if m_role:
            role_type = m_role.group(1)
            name_val = m_role.group(2)
            if not self._literal_exists_in_sources(name_val):
                logger.warning("CLICK EXTRACT | rejected role name literal: %r", name_val)
                return None
            return ExtractedLocator(
                strategy=LocatorStrategy.role,
                value=f'"{role_type}", name="{name_val}"',
            )

        # placeholder("...")
        m_placeholder = re.match(r'^placeholder\(\s*["\']([^"\']+)["\']\s*\)', hint_raw, re.IGNORECASE)
        if m_placeholder:
            val = m_placeholder.group(1)
            if not self._literal_exists_in_sources(val):
                logger.warning("CLICK EXTRACT | rejected placeholder literal: %r", val)
                return None
            return ExtractedLocator(
                strategy=LocatorStrategy.placeholder,
                value=val,
            )

        # label("...")
        m_label = re.match(r'^label\(\s*["\']([^"\']+)["\']\s*\)', hint_raw, re.IGNORECASE)
        if m_label:
            val = m_label.group(1)
            if not self._literal_exists_in_sources(val):
                logger.warning("CLICK EXTRACT | rejected label literal: %r", val)
                return None
            return ExtractedLocator(
                strategy=LocatorStrategy.label,
                value=val,
            )

        # css("...")
        m_css = re.match(r'^css\(\s*["\']([^"\']+)["\']\s*\)', hint_raw, re.IGNORECASE)
        if m_css:
            val = m_css.group(1)
            return ExtractedLocator(
                strategy=LocatorStrategy.css,
                value=val,
            )

        # xpath("...")
        m_xpath = re.match(r'^xpath\(\s*["\']([^"\']+)["\']\s*\)', hint_raw, re.IGNORECASE)
        if m_xpath:
            val = m_xpath.group(1)
            return ExtractedLocator(
                strategy=LocatorStrategy.xpath,
                value=val,
            )

        # test_id("...")
        m_testid = re.match(r'^test_id\(\s*["\']([^"\']+)["\']\s*\)', hint_raw, re.IGNORECASE)
        if m_testid:
            val = m_testid.group(1)
            if not self._literal_exists_in_sources(val):
                logger.warning("CLICK EXTRACT | rejected test_id literal: %r", val)
                return None
            return ExtractedLocator(
                strategy=LocatorStrategy.test_id,
                value=val,
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
                    "CLICK EXTRACT | rejected invented text literal: %r",
                    val,
                )
                return None

            return ExtractedLocator(
                strategy=LocatorStrategy.text,
                value=val,
            )

        return None
