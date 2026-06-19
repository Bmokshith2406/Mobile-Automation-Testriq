# app/utils/locator_utils.py
"""
Centralized Locator Utilities

Provides consistent locator validation and normalization
across all extractors and services.
"""

import re
from typing import Optional, Tuple
from app.models.cir import LocatorStrategy, CIRLocator


# =====================================================
# ARIA ROLE CONTRACT
# =====================================================

VALID_ARIA_ROLES = {
    "button", "link", "textbox", "checkbox", "radio",
    "combobox", "listbox", "option", "tab", "menuitem",
    "heading", "img", "row", "cell", "gridcell",
    "navigation", "banner", "contentinfo", "main",
    "form", "search", "dialog", "alert", "status",
}


# =====================================================
# ESCAPING / NORMALIZATION
# =====================================================

def escape_css_identifier(value: str) -> str:
    """
    Escape special characters in CSS identifiers.
    """
    return re.sub(r'([^a-zA-Z0-9_-])', r'\\\1', value)


def normalize_id_to_css(id_value: str) -> str:
    """
    Convert an ID locator to a CSS selector.
    """
    cleaned = id_value.lstrip("#").strip()
    if not cleaned:
        return ""
    escaped = escape_css_identifier(cleaned)
    return f"#{escaped}"


# =====================================================
# SYNTAX VALIDATION
# =====================================================

def is_valid_xpath(value: str) -> bool:
    if not value:
        return False

    value = value.strip()

    if not (value.startswith("//") or value.startswith(".//")):
        return False

    if value.count("[") != value.count("]"):
        return False

    if (value.count("'") % 2 != 0) or (value.count('"') % 2 != 0):
        return False

    if "[]" in value:
        return False

    return True




def is_valid_css_selector(value: str) -> bool:
    if not value:
        return False
        
    value = value.strip()
    
    if value.count("(") != value.count(")"):
        return False
    
    if (value.count("'") % 2 != 0) or (value.count('"') % 2 != 0):
        return False
    
    if value.count("[") != value.count("]"):
        return False
    
    dangerous_patterns = [
        ":focus",
        ":hover",
        ":active",
        "::before",
        "::after",
    ]
    for pattern in dangerous_patterns:
        if pattern in value.lower():
            return False
    
    return True


# =====================================================
# ROLE CONTRACT (FIXED)
# =====================================================

def is_valid_role_locator(value: str) -> bool:
    if not value:
        return False

    parts = [p.strip() for p in value.split("|") if p.strip()]

    role = None
    name = None

    # Case: role|heading|name|Text
    if (
        len(parts) == 4
        and parts[0].lower() == "role"
        and parts[2].lower() == "name"
    ):
        role = parts[1]
        name = parts[3]

    # Case: role|name|Text  → default role
    elif len(parts) == 3 and parts[0].lower() == "role" and parts[1].lower() == "name":
        role = "button"
        name = parts[2]

    # Case: heading|name|Text
    elif len(parts) == 3 and parts[1].lower() == "name":
        role, _, name = parts

    # Case: role|heading|Text
    elif len(parts) == 3 and parts[0].lower() == "role":
        _, role, name = parts

    # Case: heading|Text
    elif len(parts) == 2:
        role, name = parts

    # Case: Text → default role
    elif len(parts) == 1:
        role = "button"
        name = parts[0]

    else:
        return False

    if not role or not name:
        return False

    return role.lower() in VALID_ARIA_ROLES



# =====================================================
# STRUCTURAL REPAIR (LLM HARDENING)
# =====================================================

def normalize_llm_locator_fields(
    strategy: str,
    value: Optional[str],
) -> Tuple[str, Optional[str]]:
    """
    Repairs malformed locator fields from LLM output.

    Example:
        strategy = "role|name"
        value    = "Loan Approved"

    Becomes:
        strategy = "role"
        value    = "Loan Approved"
    """

    if not strategy:
        return strategy, value

    s = strategy.strip().lower()
    
    if s.startswith("locatorstrategy."):
        s = s.replace("locatorstrategy.", "")

    # LLM sometimes emits "role|name", "role|button", etc.
    if s.startswith("role|"):
        return "role", value

    return s, value


# =====================================================
# COMPREHENSIVE VALIDATION
# =====================================================

def is_valid_locator(locator: Optional[CIRLocator]) -> bool:
    if not locator or not locator.locator_value:
        return False
    
    value = locator.locator_value.strip()
    
    if not value:
        return False

    # Framework profile check
    try:
        from app.core.config import get_settings
        from app.core.framework_profiles import get_framework_profile
        settings = get_settings()
        profile = get_framework_profile(settings.AUTOMATION_FRAMEWORK)
        
        if locator.locator_strategy in profile.forbidden_strategies:
            return False
        if locator.locator_strategy not in profile.allowed_strategies:
            return False
    except Exception:
        pass  # Fallback gracefully if core config is missing in raw unit testing
    
    if value.count("(") != value.count(")"):
        return False
    
    if (value.count("'") % 2 != 0) or (value.count('"') % 2 != 0):
        return False
    
    if locator.locator_strategy == LocatorStrategy.xpath:
        return is_valid_xpath(value)
    
    elif locator.locator_strategy == LocatorStrategy.css:
        return is_valid_css_selector(value)
    
    elif locator.locator_strategy == LocatorStrategy.id:
        return bool(value.strip())
    
    elif locator.locator_strategy == LocatorStrategy.role:
        return is_valid_role_locator(value)
    
    return True


# =====================================================
# CANONICAL NORMALIZATION
# =====================================================

def normalize_locator(
    strategy: LocatorStrategy,
    value: str,
) -> tuple[LocatorStrategy, str]:
    """
    Normalize a locator to its canonical form.

    - Converts ID locators to CSS selectors
    - Cleans up whitespace
    """
    value = value.strip()
    
    if strategy == LocatorStrategy.id:
        return (LocatorStrategy.css, normalize_id_to_css(value))
    
    return (strategy, value)

