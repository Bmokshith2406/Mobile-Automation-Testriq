import re
from typing import Optional
import logging

from app.models.cir import LocatorStrategy, AssertionType, CIRWait, WaitCondition
from app.models.extraction import ExtractedLocator, ExtractedValue, ExtractedAssertion
from app.utils.locator_utils import escape_css_identifier

logger = logging.getLogger("script_parser")

class ScriptParser:
    """
    Unified multi-framework deterministic script parser.
    Supports Playwright, Selenium, Cypress, and Appium syntax.
    """

    @staticmethod
    def extract_locator(script: Optional[str]) -> Optional[ExtractedLocator]:
        if not script:
            return None

        # -------------------------
        # Playwright Locators
        # -------------------------
        # 1. get_by_test_id
        m = re.search(r"get_by_test_id\(\s*['\"]([^'\"]+)['\"]\s*\)", script)
        if m:
            return ExtractedLocator(locator_strategy=LocatorStrategy.test_id, locator_value=m.group(1))

        # 2a. get_by_label
        m = re.search(r"get_by_label\(\s*['\"]([^'\"]+)['\"]\s*\)", script)
        if m:
            return ExtractedLocator(locator_strategy=LocatorStrategy.label, locator_value=m.group(1))

        # 2b. get_by_placeholder
        m = re.search(r"get_by_placeholder\(\s*['\"]([^'\"]+)['\"]\s*\)", script)
        if m:
            return ExtractedLocator(locator_strategy=LocatorStrategy.placeholder, locator_value=m.group(1))

        # 2c. get_by_text
        m = re.search(r"get_by_text\(\s*['\"]([^'\"]+)['\"]\s*\)", script)
        if m:
            return ExtractedLocator(locator_strategy=LocatorStrategy.text, locator_value=m.group(1))

        # 2. get_by_role
        m = re.search(r"get_by_role\(\s*['\"]([^'\"]+)['\"]\s*,\s*name\s*=\s*['\"]([^'\"]+)['\"]\s*\)", script)
        if m:
            return ExtractedLocator(locator_strategy=LocatorStrategy.role, locator_value=f"{m.group(1)}|{m.group(2)}")

        # 3. Standard Playwright locator methods
        # Added type, press, select_option
        pw_methods = ["fill", "type", "click", "wait_for_selector", "locator", "select_option", "press", "check", "uncheck"]
        for method in pw_methods:
            # Handle possible nested quotes: regex looks for start quote and matching end quote
            m = re.search(rf"{method}\(\s*([\"'])(.*?)\1", script)
            if m:
                val = m.group(2)
                # Heuristic for xpath vs css
                strat = LocatorStrategy.xpath if val.startswith("//") or val.startswith(".//") else LocatorStrategy.css
                return ExtractedLocator(locator_strategy=strat, locator_value=val)

        # -------------------------
        # Cypress Locators
        # -------------------------
        # cy.get, cy.contains, cy.xpath
        m = re.search(r"cy\.get\(\s*([\"'])(.*?)\1", script)
        if m:
            return ExtractedLocator(locator_strategy=LocatorStrategy.css, locator_value=m.group(2))
        m = re.search(r"cy\.xpath\(\s*([\"'])(.*?)\1", script)
        if m:
            return ExtractedLocator(locator_strategy=LocatorStrategy.xpath, locator_value=m.group(2))

        # -------------------------
        # Appium Locators
        # -------------------------
        # Keep native Appium locator strategies. Appium does not support CSS
        # selectors, so ACCESSIBILITY_ID maps to CIR test_id and ID remains ID.
        appium_pattern_map = [
            (r"AppiumBy\.ACCESSIBILITY_ID\s*,\s*([\"'])(.*?)\1", LocatorStrategy.test_id),
            (r"AppiumBy\.ID\s*,\s*([\"'])(.*?)\1", LocatorStrategy.id),
            (r"AppiumBy\.XPATH\s*,\s*([\"'])(.*?)\1", LocatorStrategy.xpath),
            (r"AppiumBy\.CLASS_NAME\s*,\s*([\"'])(.*?)\1", LocatorStrategy.class_name),
            (r"AppiumBy\.IOS_CLASS_CHAIN\s*,\s*([\"'])(.*?)\1", LocatorStrategy.ios_class_chain),
            (r"AppiumBy\.IOS_PREDICATE_STRING\s*,\s*([\"'])(.*?)\1", LocatorStrategy.ios_predicate_string),
            (r"AppiumBy\.ANDROID_UIAUTOMATOR\s*,\s*([\"'])(.*?)\1", LocatorStrategy.uiautomator),
        ]

        for pattern, strategy in appium_pattern_map:
            match = re.search(pattern, script)
            if not match:
                continue

            value = match.group(2).strip()
            if value:
                return ExtractedLocator(locator_strategy=strategy, locator_value=value)

        # -------------------------
        # Selenium Locators
        # -------------------------
        pattern_map = [
            (r"By\.ID\s*,\s*([\"'])(.*?)\1", LocatorStrategy.id),
            (r"By\.NAME\s*,\s*([\"'])(.*?)\1", LocatorStrategy.name),
            (r"By\.XPATH\s*,\s*([\"'])(.*?)\1", LocatorStrategy.xpath),
            (r"By\.CSS_SELECTOR\s*,\s*([\"'])(.*?)\1", LocatorStrategy.css),
            (r"By\.CLASS_NAME\s*,\s*([\"'])(.*?)\1", LocatorStrategy.class_name),
            (r"By\.TAG_NAME\s*,\s*([\"'])(.*?)\1", LocatorStrategy.tag),
        ]

        for pattern, strategy in pattern_map:
            match = re.search(pattern, script)
            if not match:
                continue

            value = match.group(2).strip()
            if not value:
                continue

            # Convert to CSS if possible for CIR compatibility downstream, or keep original
            if strategy == LocatorStrategy.id:
                escaped = escape_css_identifier(value)
                return ExtractedLocator(locator_strategy=LocatorStrategy.css, locator_value=f"#{escaped}")

            if strategy == LocatorStrategy.name:
                escaped = escape_css_identifier(value)
                return ExtractedLocator(locator_strategy=LocatorStrategy.css, locator_value=f'[name="{escaped}"]')

            return ExtractedLocator(locator_strategy=strategy, locator_value=value)

        return None

    @staticmethod
    def extract_value(script: Optional[str]) -> Optional[ExtractedValue]:
        if not script:
            return None

        # 1. Look for explicit keyword value= (Playwright)
        m = re.search(r"select_option\([^)]*value\s*=\s*([\"'])(.*?)\1", script)
        if m:
            return ExtractedValue(value=m.group(2), mode="value")

        # 2. Look for index= (Playwright)
        m = re.search(r"select_option\([^)]*index\s*=\s*(\d+)", script)
        if m:
            return ExtractedValue(value=m.group(1), mode="index")

        # 3. Look for label= (Playwright)
        m = re.search(r"select_option\([^)]*label\s*=\s*([\"'])(.*?)\1", script)
        if m:
            return ExtractedValue(value=m.group(2), mode="label")

        # 4. Two positional arguments: fill/type("selector", "value")
        for method in ["fill", "type", "select_option"]:
            # e.g., fill("selector", "value")
            m = re.search(rf"{method}\(\s*(?:[\"'].*?[\"'])\s*,\s*([\"'])(.*?)\1\s*\)", script)
            if m:
                return ExtractedValue(value=m.group(2), mode="value")

        # 5. One positional argument (chained locator) or generic selenium send_keys
        for method in ["fill", "type", "select_option", "send_keys"]:
            # e.g., .fill("value")
            m = re.search(rf"{method}\(\s*([\"'])(.*?)\1\s*\)", script)
            if m:
                return ExtractedValue(value=m.group(2), mode="value")

        # 6. Cypress type
        m = re.search(r"\.type\(\s*([\"'])(.*?)\1\s*\)", script)
        if m:
            return ExtractedValue(value=m.group(2), mode="value")
            
        # 7. Cypress select
        m = re.search(r"\.select\(\s*([\"'])(.*?)\1\s*\)", script)
        if m:
            return ExtractedValue(value=m.group(2), mode="value")

        return None

    @staticmethod
    def extract_assertion(script: Optional[str]) -> Optional[ExtractedAssertion]:
        if not script:
            return None

        # Playwright expects
        if "expect(" in script:
            url_match = re.search(r"https?://[^\s'\"`)>,]+", script)
            if url_match:
                path = re.sub(r"https?://[^/]+", "", url_match.group(0)).split("?")[0].strip("/")
                if path:
                    return ExtractedAssertion(
                        assert_type=AssertionType.url_contains,
                        expected_value=path,
                        locator=None,
                        wait=CIRWait(condition=WaitCondition.url_contains, timeout=10)
                    )
            
            loc = ScriptParser.extract_locator(script)
            if "to_be_visible" in script:
                return ExtractedAssertion(
                    assert_type=AssertionType.element_is_visible,
                    expected_value=None,
                    locator=loc,
                    wait=CIRWait(condition=WaitCondition.visible, timeout=10)
                )
            
            m_val = re.search(r"to_(?:have|contain)_text\(\s*([\"'])(.*?)\1\s*\)", script)
            if m_val:
                atype = AssertionType.text_equals if "to_have_text" in script else AssertionType.text_contains
                return ExtractedAssertion(
                    assert_type=atype,
                    expected_value=m_val.group(2),
                    locator=loc,
                    wait=CIRWait(condition=WaitCondition.visible, timeout=10)
                )

        # Cypress assertions
        if ".should(" in script:
            loc = ScriptParser.extract_locator(script)
            if "'be.visible'" in script or '"be.visible"' in script:
                return ExtractedAssertion(
                    assert_type=AssertionType.element_is_visible,
                    expected_value=None,
                    locator=loc,
                    wait=CIRWait(condition=WaitCondition.visible, timeout=10)
                )
            m_val = re.search(r"\.should\(\s*[\"'](?:have\.text|contain)[\"']\s*,\s*([\"'])(.*?)\1\s*\)", script)
            if m_val:
                atype = AssertionType.text_equals if "have.text" in script else AssertionType.text_contains
                return ExtractedAssertion(
                    assert_type=atype,
                    expected_value=m_val.group(2),
                    locator=loc,
                    wait=CIRWait(condition=WaitCondition.visible, timeout=10)
                )
            m_url = re.search(r"cy\.url\(\)\.should\(\s*[\"']include[\"']\s*,\s*([\"'])(.*?)\1\s*\)", script)
            if m_url:
                return ExtractedAssertion(
                    assert_type=AssertionType.url_contains,
                    expected_value=m_url.group(2),
                    locator=None,
                    wait=CIRWait(condition=WaitCondition.url_contains, timeout=10)
                )

        return None

