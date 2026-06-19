from typing import Optional
import logging
import re

from app.models.extraction import ExtractedLocator, ExtractedValue
from app.models.cir import LocatorStrategy
from app.core.json_schemas import LOCATOR_SCHEMA, SELECT_VALUE_SCHEMA
from app.prompts.templates import PromptTemplates
from app.utils.locator_utils import escape_css_identifier, is_valid_xpath, normalize_llm_locator_fields
from app.services.build_helpers.base_extractor import BaseExtractor
from app.services.build_helpers.script_parser import ScriptParser

logger = logging.getLogger("select_extractor")

class SelectActionExtractor(BaseExtractor):
    """
    SEALED CIR-SAFE Select Action Extractor
    """

    async def extract_locator(
        self,
        intent: str,
        matched_script: Optional[str],
        *,
        use_cache: bool = True,
    ) -> Optional[ExtractedLocator]:

        deterministic = ScriptParser.extract_locator(matched_script)
        if deterministic and self._is_valid_locator(deterministic):
            return deterministic

        if not intent or not intent.strip():
            return None

        prompt = PromptTemplates.select_locator(intent=intent, script=matched_script)

        llm_locator = await self._extract_with_llm(
            prompt,
            purpose="select_locator_extraction",
            build_fn=self._build_locator_from_llm,
            validate_fn=self._is_valid_locator,
            use_cache=use_cache,
            schema=LOCATOR_SCHEMA,
        )

        if llm_locator:
            return llm_locator

        inferred = self._infer_locator_from_text(intent)
        if inferred and self._is_valid_locator(inferred):
            logger.warning("Select locator fallback used | intent=%s", intent)
            return inferred

        logger.warning("Select locator failed completely")
        return None

    async def extract_value(
        self,
        intent: str,
        matched_script: Optional[str],
        *,
        use_cache: bool = True,
    ) -> Optional[ExtractedValue]:

        deterministic = ScriptParser.extract_value(matched_script)
        if deterministic and self._is_valid_value(deterministic):
            return deterministic

        if not intent or not intent.strip():
            return None

        prompt = PromptTemplates.select_value(intent=intent, script=matched_script)

        llm_value = await self._extract_with_llm(
            prompt,
            purpose="select_value_extraction",
            build_fn=self._build_value_from_llm,
            validate_fn=self._is_valid_value,
            use_cache=use_cache,
            schema=SELECT_VALUE_SCHEMA,
        )

        if llm_value:
            return llm_value

        inferred = self._infer_value_from_text(intent)
        if inferred and self._is_valid_value(inferred):
            logger.warning("Select value fallback used | intent=%s", intent)
            return inferred

        logger.warning("Select value failed completely")
        return None

    def _infer_locator_from_text(self, intent: str) -> Optional[ExtractedLocator]:
        tokens = re.findall(r"[a-zA-Z_][a-zA-Z0-9_-]*", intent.lower())
        for t in tokens:
            if t in {"country", "state", "city", "category", "type"}:
                escaped = escape_css_identifier(t)
                return ExtractedLocator(
                    locator_strategy=LocatorStrategy.css,
                    locator_value=f'select[name="{escaped}"]',
                )
        return None

    def _infer_value_from_text(self, intent: str) -> Optional[ExtractedValue]:
        match = re.search(r"select\s+(.*?)\s+(from|in)", intent.lower())
        if match:
            return ExtractedValue(value=match.group(1).strip().title(), mode="label")

        quoted = re.search(r'"([^"]+)"', intent)
        if quoted:
            return ExtractedValue(value=quoted.group(1), mode="label")

        return None

    def _build_locator_from_llm(self, data: Optional[dict]) -> Optional[ExtractedLocator]:
        if not isinstance(data, dict):
            return None

        raw_strategy = str(data.get("locator_strategy") or "").strip()
        raw_value = str(data.get("locator_value") or "").strip()

        raw_strategy, raw_value = normalize_llm_locator_fields(raw_strategy, raw_value)

        if not raw_strategy or not raw_value:
            return None

        strategy = self._normalize_strategy(raw_strategy)
        if not strategy:
            return None

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

        if strategy == LocatorStrategy.role:
            fixed = self._normalize_role_locator(raw_value)
            if fixed is None:
                return None
            return ExtractedLocator(
                locator_strategy=LocatorStrategy.role,
                locator_value=fixed,
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

        if "value" in data:
            value = data.get("value")
        elif "option" in data:
            value = data.get("option")
        elif "text" in data:
            value = data.get("text")
        else:
            value = None

        mode = data.get("mode")

        if value is None or mode is None:
            return None

        value = str(value).strip()
        if not value:
            return None

        if mode not in {"value", "label", "index"}:
            return None

        if mode == "index" and not value.isdigit():
            return None

        return ExtractedValue(value=value, mode=mode)

