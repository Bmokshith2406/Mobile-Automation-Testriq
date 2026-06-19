from typing import Optional
import logging
import re

from app.models.extraction import ExtractedLocator
from app.models.cir import LocatorStrategy
from app.core.json_schemas import LOCATOR_SCHEMA
from app.prompts.templates import PromptTemplates
from app.utils.locator_utils import escape_css_identifier, is_valid_xpath, normalize_llm_locator_fields
from app.services.build_helpers.base_extractor import BaseExtractor
from app.services.build_helpers.script_parser import ScriptParser

logger = logging.getLogger("click_extractor")

class ClickActionExtractor(BaseExtractor):
    """
    SEALED CLICK LOCATOR EXTRACTOR (CIR-SAFE)
    """

    async def extract_locator(
        self,
        intent: str,
        matched_script: Optional[str],
        *,
        use_cache: bool = True,
    ) -> Optional[ExtractedLocator]:

        logger.debug("CLICK EXTRACTOR START | intent=%r | has_script=%s", intent, bool(matched_script))

        deterministic = ScriptParser.extract_locator(matched_script)
        if deterministic and self._is_valid_locator(deterministic):
            return deterministic

        if not intent or not intent.strip():
            return None

        prompt = PromptTemplates.click_locator(intent=intent, script=matched_script)

        locator = await self._extract_with_llm(
            prompt,
            purpose="click_locator_extraction",
            build_fn=self._build_locator_from_llm,
            validate_fn=self._is_valid_locator,
            use_cache=use_cache,
            schema=LOCATOR_SCHEMA,
        )

        if locator:
            return locator

        logger.warning("Click locator failed")
        return None

    def _build_locator_from_llm(self, data: Optional[dict]) -> Optional[ExtractedLocator]:
        if not isinstance(data, dict):
            return None

        raw_strategy = str(data.get("locator_strategy") or "").strip()
        raw_value = str(data.get("locator_value") or "").strip()

        raw_strategy, raw_value = normalize_llm_locator_fields(raw_strategy, raw_value)

        if not raw_strategy or raw_value is None:
            return None

        raw_value = str(raw_value).strip()
        if not raw_value:
            return None

        strategy = self._normalize_strategy(raw_strategy)
        if not strategy:
            return None

        if strategy == LocatorStrategy.role:
            fixed = self._normalize_role_locator(raw_value)
            if fixed is None:
                return None
            return ExtractedLocator(
                locator_strategy=LocatorStrategy.role,
                locator_value=fixed,
            )

        if strategy == LocatorStrategy.id:
            raw_value = raw_value.replace("id=", "").replace("ID=", "").lstrip("#").strip()
            if not raw_value:
                return None
            escaped = escape_css_identifier(raw_value)
            return ExtractedLocator(
                locator_strategy=LocatorStrategy.css,
                locator_value=f"#{escaped}",
            )

        if strategy == LocatorStrategy.name:
            escaped = escape_css_identifier(raw_value)
            return ExtractedLocator(
                locator_strategy=LocatorStrategy.css,
                locator_value=f'[name="{escaped}"]',
            )

        if strategy == LocatorStrategy.xpath:
            if not is_valid_xpath(raw_value):
                return None

        return ExtractedLocator(
            locator_strategy=strategy,
            locator_value=raw_value,
        )

