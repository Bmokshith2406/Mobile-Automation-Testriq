from typing import Optional, Tuple
import logging
import re

from app.core.llm_executor import LLMExecutor
from app.core.dom_pruner import DomPruner
from app.core.prompts import build_type_extractor_prompt
from app.models.extraction import ExtractedLocator, ExtractedValue
from app.models.cir import LocatorStrategy
from app.services.extractors.BaseExtractor import BaseExtractor

logger = logging.getLogger("type_extractor")


class TypeActionExtractor(BaseExtractor):
    """
    TYPE action evidence extractor for STEP REPAIR.
    """

    MAX_DOM_CHARS = 700

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
                "TYPE EXTRACT | rejected LLM hint: %r",
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
        if pruned_dom:
            pruned_dom = pruned_dom[: self.MAX_DOM_CHARS]
        self._last_dom_snapshot = pruned_dom or ""

        prompt = build_type_extractor_prompt(
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

        if not lowered.startswith("type:"):
            return None, None

        value_match = re.search(r'value\("([^"]+)"\)', raw)
        if not value_match:
            return None, None

        value_kind = value_match.group(1)
        value = ExtractedValue(value=value_kind)

        locator_part = raw.split("value(", 1)[0].strip()

        if (framework or "").strip().lower() == "appium":
            locator_hint = locator_part.split(":", 1)[1].strip()
            locator = self._appium_locator_from_hint(locator_hint)
            return (locator, value) if locator else (None, None)

        if locator_part.lower().startswith("type:label("):
            loc = self._extract_quoted(locator_part)
            if not loc:
                return None, None

            return (
                ExtractedLocator(
                    strategy=LocatorStrategy.label,
                    value=loc,
                ),
                value,
            )

        if locator_part.lower().startswith("type:placeholder("):
            loc = self._extract_quoted(locator_part)
            if not loc:
                return None, None

            return (
                ExtractedLocator(
                    strategy=LocatorStrategy.placeholder,
                    value=loc,
                ),
                value,
            )

        if locator_part.lower().startswith("type:role("):
            loc = self._extract_quoted(locator_part)
            if not loc:
                return None, None

            return (
                ExtractedLocator(
                    strategy=LocatorStrategy.role,
                    value=loc,
                ),
                value,
            )

        logger.warning(
            "TYPE EXTRACT | unsupported locator grammar: %s",
            locator_part,
        )
        return None, None
