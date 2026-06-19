from typing import Optional
import logging
import re

from app.models.extraction import ExtractedLocator, ExtractedValue
from app.models.cir import LocatorStrategy
from app.core.json_schemas import LOCATOR_SCHEMA, TYPE_VALUE_SCHEMA
from app.prompts.templates import PromptTemplates
from app.utils.locator_utils import escape_css_identifier, is_valid_xpath, normalize_llm_locator_fields
from app.services.build_helpers.base_extractor import BaseExtractor
from app.services.build_helpers.script_parser import ScriptParser

logger = logging.getLogger("type_extractor")

class TypeActionExtractor(BaseExtractor):
    """
    SEALED CIR-SAFE TYPE EXTRACTOR (ROLE-SAFE)
    """

    async def extract_locator(
        self,
        intent: str,
        matched_script: Optional[str],
        *,
        use_cache: bool = True,
    ) -> Optional[ExtractedLocator]:

        logger.debug("TYPE LOCATOR START | intent=%r | has_script=%s", intent, bool(matched_script))

        deterministic_locator = ScriptParser.extract_locator(matched_script)
        if deterministic_locator and self._is_valid_locator(deterministic_locator):
            return deterministic_locator

        if not intent or not intent.strip():
            return None

        prompt = PromptTemplates.type_locator(intent=intent, script=matched_script)

        locator = await self._extract_with_llm(
            prompt,
            purpose="type_locator_extraction",
            build_fn=self._build_locator_from_llm,
            validate_fn=self._is_valid_locator,
            use_cache=use_cache,
            schema=LOCATOR_SCHEMA,
        )

        if locator:
            return locator

        inferred = self._infer_locator_from_text(intent)
        if inferred and self._is_valid_locator(inferred):
            logger.warning("Type locator fallback used | intent=%r", intent)
            return inferred

        logger.warning("Type locator failed completely")
        return None

    async def extract_value(
        self,
        intent: str,
        matched_script: Optional[str],
        *,
        use_cache: bool = True,
    ) -> Optional[ExtractedValue]:

        deterministic_value = ScriptParser.extract_value(matched_script)
        if deterministic_value and self._is_valid_value(deterministic_value):
            return deterministic_value

        if not intent or not intent.strip():
            return None

        prompt = PromptTemplates.type_value(intent=intent, script=matched_script)

        value = await self._extract_with_llm(
            prompt,
            purpose="type_value_extraction",
            build_fn=self._build_value_from_llm,
            validate_fn=self._is_valid_value,
            use_cache=use_cache,
            schema=TYPE_VALUE_SCHEMA,
        )

        if value:
            return value

        inferred = self._infer_value_from_text(intent)
        if inferred and self._is_valid_value(inferred):
            logger.warning("Type value fallback used | intent=%r", intent)
            return inferred

        logger.warning("Type value failed completely")
        return None

    def _infer_locator_from_text(self, intent: str) -> Optional[ExtractedLocator]:
        match = re.search(r"into\s+(?:the\s+)?([\w\s]+?)(?:\s+field)?$", intent.lower())
        if match:
            name = match.group(1).strip().replace(" ", "_")
            escaped = escape_css_identifier(name)
            return ExtractedLocator(
                locator_strategy=LocatorStrategy.css,
                locator_value=f'input[name="{escaped}"]',
            )
        return None

    def _infer_value_from_text(self, intent: str) -> Optional[ExtractedValue]:
        quoted = re.search(r'"([^"]+)"', intent)
        if quoted:
            return ExtractedValue(value=quoted.group(1))

        match = re.search(r"(?:type|enter|input)\s+(.+)$", intent.lower())
        if match:
            return ExtractedValue(value=match.group(1).strip())

        return None

    def _build_locator_from_llm(self, data: Optional[dict]) -> Optional[ExtractedLocator]:
        if not isinstance(data, dict):
            return None

        raw_strategy = str(data.get("locator_strategy") or "").strip()
        raw_value = str(data.get("locator_value") or "").strip()

        raw_strategy, raw_value = normalize_llm_locator_fields(raw_strategy, raw_value)

        if not raw_strategy or raw_value is None:
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
            raw_value = raw_value.replace("id=", "").lstrip("#").strip()
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

    def _build_value_from_llm(self, data: Optional[dict]) -> Optional[ExtractedValue]:
        if not isinstance(data, dict):
            return None

        value = data.get("value")
        if value is None:
            return None

        value = str(value).strip()
        if not value:
            return None

        return ExtractedValue(value=value)

