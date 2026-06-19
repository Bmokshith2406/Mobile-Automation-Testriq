# app/services/normalizer.py
"""
CIR Normalizer - DEPRECATED

This module is deprecated and will be removed in a future version.
Use app/utils/locator_utils.py for locator normalization instead.

The functionality has been integrated into:
- app/utils/locator_utils.py - Locator validation and normalization
- app/services/atomic_normalizer.py - Atomic action normalization
"""

import warnings
import re
from typing import Any

from app.models.cir import (
    LocatorStrategy,
    AssertionType,
    CIRLocator,
    CIRAssertion,
)

warnings.warn(
    "CIRNormalizer is deprecated. Use locator_utils and atomic_normalizer instead.",
    DeprecationWarning,
    stacklevel=2,
)


class NormalizationError(Exception):
    """Error during normalization."""
    pass


class CIRNormalizer:
    """
    DEPRECATED: Normalizes raw LLM-extracted data into strict CIR enums.

    Use locator_utils.normalize_locator() and atomic_normalizer instead.
    """

    def __init__(self):
        warnings.warn(
            "CIRNormalizer is deprecated. Use locator_utils instead.",
            DeprecationWarning,
            stacklevel=2,
        )
    

    LOCATOR_RULES = [
        (r"^xpath$", LocatorStrategy.xpath),
        (r"^css$|^css selector$", LocatorStrategy.css),
        (r"^id$", LocatorStrategy.id),
        (r"^class$|^classname$|^class name$", LocatorStrategy.css),
        (r"^tag$|^tagname$", LocatorStrategy.css),
        (r"^name$", LocatorStrategy.css),
    ]

    ASSERTION_RULES = [
        (r"url.*contain", AssertionType.url_contains),
        (r"text.*contain", AssertionType.text_contains),
        (r"text.*equal", AssertionType.text_equals),
        (r"visible|shown|displayed|appears", AssertionType.element_is_visible),
    ]

    def normalize_locator(self, raw: Any) -> CIRLocator:
        """Normalize locator - use locator_utils.normalize_locator instead."""
        from app.utils.locator_utils import normalize_locator as new_normalize
        
        raw_strategy = self._get(raw, "locator_strategy")
        raw_value = self._get(raw, "locator_value")

        if not raw_strategy or not raw_value:
            raise NormalizationError(
                f"Locator normalization failed: strategy={raw_strategy}, value={raw_value}"
            )

        strategy_raw = self._clean(str(raw_strategy))
        value_raw = str(raw_value).strip()

        if not value_raw:
            raise NormalizationError("Empty locator_value")

        # Use new utility
        try:
            strategy_enum = LocatorStrategy(strategy_raw)
        except ValueError:
            for pattern, enum in self.LOCATOR_RULES:
                if re.fullmatch(pattern, strategy_raw):
                    strategy_enum = enum
                    break
            else:
                raise NormalizationError(f"Unsupported locator strategy '{raw_strategy}'")
        
        new_strategy, new_value = new_normalize(strategy_enum, value_raw)
        return CIRLocator(locator_strategy=new_strategy, locator_value=new_value)

    def normalize_assertion(self, raw: Any) -> CIRAssertion:
        """Normalize assertion type."""
        raw_type = self._get(raw, "assert_type") or self._get(raw, "kind")
        expected_value = self._get(raw, "expected_value")

        if not raw_type:
            raise NormalizationError("Missing assertion type")

        type_raw = self._clean(str(raw_type))

        for pattern, enum in self.ASSERTION_RULES:
            if re.search(pattern, type_raw):
                assertion = CIRAssertion(
                    assert_type=enum,
                    expected_value=(
                        str(expected_value).strip()
                        if expected_value is not None
                        else None
                    ),
                )
                self._validate_assertion(assertion)
                return assertion

        raise NormalizationError(f"Unsupported assertion type '{raw_type}'")

    def _validate_assertion(self, assertion: CIRAssertion) -> None:
        """Validate assertion has required fields."""
        if assertion.assert_type == AssertionType.url_contains:
            if not assertion.expected_value:
                raise NormalizationError("url_contains assertion requires expected_value")

        if assertion.assert_type == AssertionType.element_is_visible:
            if assertion.expected_value:
                raise NormalizationError("element_is_visible must NOT have expected_value")

        if assertion.assert_type in (AssertionType.text_contains, AssertionType.text_equals):
            if not assertion.expected_value:
                raise NormalizationError(f"{assertion.assert_type.value} requires expected_value")

    def _clean(self, text: str) -> str:
        """Clean and normalize text."""
        return re.sub(r"\s+", " ", text.lower().strip())

    def _get(self, raw: Any, field: str):
        """Safely get field from dict or object."""
        if raw is None:
            return None
        if isinstance(raw, dict):
            return raw.get(field)
        return getattr(raw, field, None)

