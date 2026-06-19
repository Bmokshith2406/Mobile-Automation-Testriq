from typing import Optional
import logging
import re
import ast
from app.core.utils import extract_quoted
from app.models.cir import LocatorStrategy
from app.models.extraction import ExtractedLocator

logger = logging.getLogger("base_extractor")


class BaseExtractor:
    """
    Common base class for all action extractors.
    Provides common validation and extraction logic.
    """

    def __init__(self) -> None:
        self._last_step_intent = ""
        self._last_original_code = ""
        self._last_dom_snapshot = ""

    def _extract_quoted(self, text: str) -> Optional[str]:
        """
        Extracts the first quoted string.
        """
        return extract_quoted(text)

    def _literal_exists_in_sources(self, value: str) -> bool:
        """
        Ensures the extracted visible text exists in step intent,
        original code, or the pruned DOM snapshot.
        Case-insensitive match.
        """
        sources = [
            getattr(self, "_last_step_intent", "") or "",
            getattr(self, "_last_original_code", "") or "",
            getattr(self, "_last_dom_snapshot", "") or "",
        ]

        val_lower = value.lower()
        for src in sources:
            if val_lower in src.lower():
                return True

        return False

    def _appium_locator_from_hint(self, hint_raw: str) -> Optional[ExtractedLocator]:
        hint_raw = (hint_raw or "").strip()
        hint_lower = hint_raw.lower()

        forbidden_prefixes = (
            "role(",
            "label(",
            "placeholder(",
            "css(",
            "test_id(",
        )
        if hint_lower.startswith(forbidden_prefixes):
            logger.warning("APPIUM EXTRACT | rejected web locator grammar: %r", hint_raw)
            return None

        patterns = (
            (("id", "resource_id"), LocatorStrategy.id, True),
            (("accessibility_id", "content_desc", "content-desc", "a11y"), LocatorStrategy.test_id, True),
            (("uiautomator",), LocatorStrategy.uiautomator, False),
            (("xpath",), LocatorStrategy.xpath, False),
            (("text",), LocatorStrategy.text, True),
            # Enhanced: iOS/Android-specific mobile locator strategies
            (("ios_class_chain",), LocatorStrategy.ios_class_chain, False),
            (("ios_predicate_string",), LocatorStrategy.ios_predicate_string, False),
            (("android_data_matcher",), LocatorStrategy.android_data_matcher, False),
        )

        for names, strategy, must_exist in patterns:
            value = self._extract_strategy_value(hint_raw, names)
            if value is None:
                continue
            if must_exist and not self._literal_exists_in_sources(value):
                logger.warning("APPIUM EXTRACT | rejected invented literal: %r", value)
                return None
            return ExtractedLocator(strategy=strategy, value=value)

        value = self._extract_quoted(hint_raw)
        if value and self._literal_exists_in_sources(value):
            return ExtractedLocator(strategy=LocatorStrategy.text, value=value)

        return None

    @staticmethod
    def _extract_strategy_value(hint_raw: str, names: tuple[str, ...]) -> Optional[str]:
        value = (hint_raw or "").strip()
        value_lower = value.lower()
        for name in names:
            prefix = f"{name.lower()}("
            if not value_lower.startswith(prefix) or not value.endswith(")"):
                continue
            inner = value[len(prefix):-1].strip()
            try:
                parsed = ast.literal_eval(inner)
                return str(parsed)
            except Exception:
                quoted = re.match(r'^\s*(["\'])(.*)\1\s*$', inner, flags=re.DOTALL)
                if quoted:
                    return quoted.group(2)
        return None
