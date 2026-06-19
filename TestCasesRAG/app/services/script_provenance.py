from __future__ import annotations

from typing import Optional


FRAMEWORK_LANGUAGE_MAP = {
    "playwright": "python",
    "selenium": "python",
    "appium": "python",
    "cypress": "javascript",
}


def normalize_framework(value: Optional[str]) -> Optional[str]:
    raw_value = str(value or "").strip().lower()
    if not raw_value:
        return None

    for framework in FRAMEWORK_LANGUAGE_MAP:
        if raw_value == framework or framework in raw_value:
            return framework
    return None


def normalize_language(value: Optional[str]) -> Optional[str]:
    raw_value = str(value or "").strip().lower()
    if raw_value in {"python", "py"}:
        return "python"
    if raw_value in {"javascript", "js", "typescript", "ts"}:
        return "javascript"
    return None


def infer_framework_from_code(script_content: Optional[str]) -> Optional[str]:
    text = str(script_content or "").strip().lower()
    if not text:
        return None

    if any(token in text for token in ("cy.", "cypress.", "describe(", "it(", "beforeeach(", "aftereach(")):
        return "cypress"
    if any(token in text for token in ("from appium", "import appium", "appiumby", "appiumoptions", "appium:")):
        return "appium"
    if any(token in text for token in ("from selenium", "import selenium", "webdriverwait", "expected_conditions", "webdriver.")):
        return "selenium"
    if any(token in text for token in ("from playwright", "import playwright", "async_playwright", "locator(", "page.")):
        return "playwright"
    return None


def infer_language_from_code(script_content: Optional[str], framework: Optional[str] = None) -> Optional[str]:
    text = str(script_content or "").strip().lower()
    if text:
        if any(token in text for token in ("async def ", "def ", "from ", "import ")):
            return "python"
        if any(token in text for token in ("const ", "let ", "var ", "function ", "=>", "describe(", "it(", "cy.")):
            return "javascript"

    normalized_framework = normalize_framework(framework)
    if normalized_framework:
        return FRAMEWORK_LANGUAGE_MAP.get(normalized_framework)
    return None


def resolve_script_provenance(
    script_content: Optional[str],
    *,
    explicit_framework: Optional[str] = None,
    explicit_language: Optional[str] = None,
    structured_test_case: Optional[dict] = None,
    platform: Optional[str] = None,
    legacy_default_framework: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    framework = None
    structured = structured_test_case if isinstance(structured_test_case, dict) else {}

    for candidate in (
        explicit_framework,
        structured.get("script_framework"),
        structured.get("target_framework"),
        platform,
    ):
        framework = normalize_framework(candidate)
        if framework:
            break
    if not framework:
        framework = infer_framework_from_code(script_content)
    if not framework:
        framework = normalize_framework(legacy_default_framework)

    language = None
    for candidate in (
        explicit_language,
        structured.get("script_language"),
    ):
        language = normalize_language(candidate)
        if language:
            break
    if not language:
        language = infer_language_from_code(script_content, framework)
    if not language:
        language = normalize_language(FRAMEWORK_LANGUAGE_MAP.get(framework or ""))

    return framework, language
