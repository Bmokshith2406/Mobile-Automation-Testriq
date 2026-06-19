from __future__ import annotations

from typing import Optional


FRAMEWORK_LANGUAGE_MAP = {
    "playwright": "python",
    "selenium": "python",
    "appium": "python",
    "cypress": "javascript",
}

STORED_FRAMEWORK_FIELD = "script_framework"
STORED_LANGUAGE_FIELD = "script_language"


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


def infer_framework_from_code(raw_code: Optional[str]) -> Optional[str]:
    text = str(raw_code or "").strip().lower()
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


def infer_language_from_code(raw_code: Optional[str], framework: Optional[str] = None) -> Optional[str]:
    text = str(raw_code or "").strip().lower()
    if text:
        if any(token in text for token in ("async def ", "def ", "from ", "import ")):
            return "python"
        if any(token in text for token in ("const ", "let ", "var ", "function ", "=>", "describe(", "it(", "cy.")):
            return "javascript"

    normalized_framework = normalize_framework(framework)
    if normalized_framework:
        return FRAMEWORK_LANGUAGE_MAP.get(normalized_framework)
    return None


def resolve_code_provenance(
    raw_code: Optional[str],
    *,
    explicit_framework: Optional[str] = None,
    explicit_language: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    framework = normalize_framework(explicit_framework) or infer_framework_from_code(raw_code)

    language = normalize_language(explicit_language)
    if not language:
        language = infer_language_from_code(raw_code, framework)
    if not language and framework:
        language = FRAMEWORK_LANGUAGE_MAP.get(framework)

    return framework, language


def display_framework(framework: Optional[str]) -> str:
    normalized_framework = normalize_framework(framework)
    if not normalized_framework:
        return "automation"
    return normalized_framework


def display_language(language: Optional[str]) -> str:
    normalized_language = normalize_language(language)
    if not normalized_language:
        return "code"
    return normalized_language
