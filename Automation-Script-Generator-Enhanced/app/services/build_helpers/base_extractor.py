from typing import Any, Dict, Optional
import logging
import re

from app.core.config import get_settings
from app.core.llm_json import generate_json
from app.models.cir import LocatorStrategy, CIRWait, WaitCondition, CIRLocator
from app.models.extraction import ExtractedLocator, ExtractedValue
from app.utils.locator_utils import (
    VALID_ARIA_ROLES,
    is_valid_locator as central_is_valid_locator,
)

logger = logging.getLogger("base_extractor")
settings = get_settings()


class BaseExtractor:
    """
    UNIFIED BASE EXTRACTOR
    
    Consolidates confidence checks, role sanitation, strategy translation,
    locator validation, and wait definition methods across all extractor engines.
    """

    def __init__(self):
        self.min_confidence = settings.MIN_CONFIDENCE_THRESHOLD
        self.max_retries = settings.MAX_EXTRACTOR_RETRIES

    async def _extract_with_llm(
        self,
        prompt: str,
        purpose: str,
        build_fn,
        validate_fn,
        use_cache: bool = True,
        schema: Optional[Dict[str, Any]] = None,
    ):
        last_data = None
        for attempt in range(self.max_retries + 1):
            attempt_use_cache = use_cache and attempt == 0
            try:
                data = await generate_json(
                    prompt,
                    purpose=purpose,
                    use_cache=attempt_use_cache,
                    schema=schema,
                )
            except Exception as exc:
                logger.error(
                    "LLM error | purpose=%s | attempt=%d | error=%s",
                    purpose,
                    attempt + 1,
                    exc,
                )
                continue

            last_data = data
            confidence = self._extract_confidence(data)

            if confidence is None or confidence < self.min_confidence:
                continue

            result = build_fn(data)

            if result and validate_fn(result):
                return result

        logger.warning("Extraction failed | purpose=%s | last_data=%r", purpose, last_data)
        return None

    def _clean_role_name(self, name: str) -> str:
        name = name.strip()
        name = re.sub(r"^(name|aria-label|label)\s*=\s*", "", name, flags=re.I)
        name = name.strip("'\"")
        return name.strip()

    def _extract_confidence(self, data: Optional[dict]) -> Optional[int]:
        if not isinstance(data, dict):
            return None

        c = data.get("confidence")
        if c is None:
            return None

        try:
            c = int(c)
            return c if 0 <= c <= 100 else None
        except Exception:
            return None

    def _normalize_strategy(self, value: str) -> Optional[LocatorStrategy]:
        if not value:
            return None

        value = value.lower().strip()

        if value in ("css", "css_selector", "cssselector"):
            return LocatorStrategy.css
        if value in ("xpath", "xpath_selector"):
            return LocatorStrategy.xpath
        if value == "id":
            return LocatorStrategy.id
        if value == "name":
            return LocatorStrategy.name
        if value == "role":
            return LocatorStrategy.role
        if value in ("test_id", "testid", "data-testid"):
            return LocatorStrategy.test_id
        if value == "class":
            return LocatorStrategy.class_name
        if value == "tag":
            return LocatorStrategy.tag
        if value in ("placeholder",):
            return LocatorStrategy.placeholder
        if value in ("label",):
            return LocatorStrategy.label
        if value in ("text", "text_content", "inner_text"):
            return LocatorStrategy.text
        if value in ("uiautomator", "android_uiautomator", "androiduiautomator", "android_ui_automator"):
            return LocatorStrategy.uiautomator
        if value in ("accessibility_id", "accessibility id", "accessibilityid", "accessibility"):
            return LocatorStrategy.test_id
        if value in ("ios_class_chain", "iosclasschain", "ios_class"):
            return LocatorStrategy.ios_class_chain
        if value in ("ios_predicate_string", "nspredicate", "ios_predicate"):
            return LocatorStrategy.ios_predicate_string

        return None

    def _normalize_role_locator(self, value: str) -> Optional[str]:
        value = value.strip()
        parts = [p.strip() for p in value.split("|") if p.strip()]

        role = None
        name = None

        if len(parts) == 4 and parts[0].lower() == "role" and parts[2].lower() == "name":
            role = parts[1]
            name = parts[3]
        elif len(parts) == 3 and parts[1].lower() == "name":
            role, _, name = parts
        elif len(parts) == 3 and parts[0].lower() == "role":
            _, role, name = parts
        elif len(parts) == 2:
            role, name = parts
        elif len(parts) == 1:
            role = "button"
            name = parts[0]
        else:
            return None

        role = role.strip()
        name = self._clean_role_name(name)

        if not role or not name:
            return None

        if role.lower() not in VALID_ARIA_ROLES:
            return None

        return f"{role}|{name}"

    def _is_valid_locator(self, loc: ExtractedLocator) -> bool:
        if not loc or not loc.locator_strategy or loc.locator_value is None:
            return False
        
        cir_loc = CIRLocator(
            locator_strategy=loc.locator_strategy,
            locator_value=loc.locator_value,
        )
        return central_is_valid_locator(cir_loc)

    def _is_valid_value(self, v: ExtractedValue) -> bool:
        return bool(v and v.value and v.value.strip())

    def extract_wait(
        self,
        intent: str,
        matched_script: Optional[str],
        timeout: int = 10,
    ) -> CIRWait:
        text = (intent or "").lower()
        script = (matched_script or "").lower()

        if any(k in text for k in ("url", "redirect", "navigate", "load")):
            return CIRWait(condition=WaitCondition.url_contains, timeout=timeout)
        if any(k in text for k in ("disappear", "hidden", "gone", "close", "dismiss")):
            return CIRWait(condition=WaitCondition.hidden, timeout=timeout)
        if "wait_for_url" in script:
            return CIRWait(condition=WaitCondition.url_contains, timeout=timeout)
        if "wait_for_load_state" in script:
            return CIRWait(condition=WaitCondition.load_state, timeout=timeout)
        if "hidden" in script and "wait_for_selector" in script:
            return CIRWait(condition=WaitCondition.hidden, timeout=timeout)

        m = re.search(r"timeout\s*=\s*(\d+)", matched_script or "")
        if m:
            script_timeout = int(m.group(1))
            if script_timeout > 1000:
                script_timeout = script_timeout // 1000
            timeout = min(max(script_timeout, 1), 60)

        return CIRWait(condition=WaitCondition.visible, timeout=timeout)

