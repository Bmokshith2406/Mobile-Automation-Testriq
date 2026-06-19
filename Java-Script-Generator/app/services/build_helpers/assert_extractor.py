from typing import Optional
import re
import logging

from app.models.extraction import ExtractedAssertion, ExtractedLocator
from app.models.cir import AssertionType, LocatorStrategy, CIRWait, WaitCondition
from app.core.json_schemas import ASSERT_EXTRACTION_SCHEMA
from app.prompts.templates import PromptTemplates
from app.utils.locator_utils import escape_css_identifier, is_valid_xpath, normalize_llm_locator_fields
from app.services.build_helpers.base_extractor import BaseExtractor
from app.services.build_helpers.script_parser import ScriptParser

logger = logging.getLogger("assert_extractor")

class AssertActionExtractor(BaseExtractor):
    """
    SEALED ASSERTION EXTRACTOR (CIR-SAFE)
    """

    ASSERT_HINTS = (
        "verify", "assert", "ensure", "check",
        "should", "is visible", "is displayed",
    )

    SEARCH_HINTS = (
        "search", "results", "found",
        "filter", "list", "show",
        "display results",
    )

    async def extract(
        self,
        intent: str,
        expected: Optional[str],
        matched_script: Optional[str],
        *,
        use_cache: bool = True,
    ) -> Optional[ExtractedAssertion]:

        if not intent or not intent.strip():
            return None

        text = f"{intent} {expected or ''}".lower()
        is_search_like = any(k in text for k in self.SEARCH_HINTS)

        if "page title" in text or "title is visible" in text or "title is shown" in text:
            if expected:
                return ExtractedAssertion(
                    assert_type=AssertionType.title_contains,
                    expected_value=expected,
                    locator=None,
                    wait=self._derive_wait(AssertionType.title_contains),
                )
            return None

        deterministic = ScriptParser.extract_assertion(matched_script)
        if deterministic and self._is_valid_assertion(deterministic):
            return deterministic

        if not expected and not any(k in text for k in self.ASSERT_HINTS):
            return None

        prompt = PromptTemplates.assert_extraction(
            intent=intent,
            expected=expected,
            script=matched_script,
        )

        llm_assertion = await self._extract_with_llm(
            prompt,
            purpose="assertion_extraction",
            build_fn=self._build_assertion_from_llm,
            validate_fn=self._is_valid_assertion,
            use_cache=use_cache,
            schema=ASSERT_EXTRACTION_SCHEMA,
        )

        if llm_assertion:
            if is_search_like and llm_assertion.assert_type == AssertionType.url_contains:
                pass
            else:
                return llm_assertion

        logger.warning("Assertion extraction failed completely")
        return None

    def _normalize_assert_type(self, value: str) -> Optional[AssertionType]:
        value = value.lower().strip()
        if value.startswith("assertiontype."):
            value = value.replace("assertiontype.", "")

        if value in ("url", "url_contains", "url_match"):
            return AssertionType.url_contains
        if value in ("visible", "element_is_visible", "element_visible", "is_visible", "displayed", "shown"):
            return AssertionType.element_is_visible
        if value in ("text", "text_equals", "equals", "exact_text"):
            return AssertionType.text_equals
        if value in ("text_contains", "contains", "partial_text"):
            return AssertionType.text_contains
        if value in ("title", "title_contains", "page_title"):
            return AssertionType.title_contains
        if value in ("title_equals", "exact_title"):
            return AssertionType.title_equals

        return None

    def _build_assertion_from_llm(self, data: Optional[dict]) -> Optional[ExtractedAssertion]:
        if not isinstance(data, dict):
            return None

        raw_type = str(data.get("assert_type") or "").strip()
        if not raw_type or raw_type == "null":
            return None

        assert_type = self._normalize_assert_type(raw_type)
        if not assert_type:
            return None

        expected_value = data.get("expected_value") or data.get("expected") or data.get("text")
        expected_value = str(expected_value).strip() if expected_value else None

        if assert_type in {AssertionType.text_equals, AssertionType.text_contains, AssertionType.url_contains, AssertionType.title_contains, AssertionType.title_equals}:
            if not expected_value:
                return None

        if assert_type == AssertionType.element_is_visible:
            expected_value = None

        if assert_type in {AssertionType.url_contains, AssertionType.title_contains, AssertionType.title_equals}:
            return ExtractedAssertion(
                assert_type=assert_type,
                expected_value=expected_value,
                locator=None,
                wait=self._derive_wait(assert_type),
            )

        raw_locator = data.get("locator")

        if isinstance(raw_locator, dict):
            raw_strategy = str(raw_locator.get("locator_strategy") or "").strip()
            raw_value = str(raw_locator.get("locator_value") or "").strip()
        else:
            raw_strategy = str(data.get("locator_strategy") or "").strip()
            raw_value = str(data.get("locator_value") or "").strip()

        raw_strategy, raw_value = normalize_llm_locator_fields(raw_strategy, raw_value)

        if not raw_value:
            return None

        strategy = self._normalize_strategy(raw_strategy)
        if not strategy:
            return None

        if strategy == LocatorStrategy.role:
            fixed = self._normalize_role_locator(raw_value)
            if fixed is None:
                return None
            raw_value = fixed

        if strategy == LocatorStrategy.id:
            raw_value = raw_value.replace("id=", "").lstrip("#").strip()
            escaped = escape_css_identifier(raw_value)
            locator = ExtractedLocator(
                locator_strategy=LocatorStrategy.css,
                locator_value=f"#{escaped}",
            )
        elif strategy == LocatorStrategy.name:
            escaped = escape_css_identifier(raw_value)
            locator = ExtractedLocator(
                locator_strategy=LocatorStrategy.css,
                locator_value=f'[name="{escaped}"]',
            )
        else:
            locator = ExtractedLocator(
                locator_strategy=strategy,
                locator_value=raw_value,
            )

        return ExtractedAssertion(
            assert_type=assert_type,
            expected_value=expected_value,
            locator=locator,
            wait=self._derive_wait(assert_type),
        )

    def _is_valid_assertion(self, a: ExtractedAssertion) -> bool:
        if a.assert_type == AssertionType.element_is_visible and not a.locator:
            return False
        if a.assert_type == AssertionType.url_contains and a.locator is not None:
            return False
        if a.locator:
            return self._is_valid_locator(a.locator)
        return True

    def _derive_wait(self, assert_type: AssertionType) -> CIRWait:
        if assert_type == AssertionType.url_contains:
            return CIRWait(condition=WaitCondition.url_contains, timeout=10)
        return CIRWait(condition=WaitCondition.visible, timeout=10)

