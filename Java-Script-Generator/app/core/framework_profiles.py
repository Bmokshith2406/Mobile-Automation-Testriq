from typing import List, Set
from pydantic import BaseModel
from app.models.cir import LocatorStrategy


class FrameworkProfile(BaseModel):
    name: str
    locator_priority: List[LocatorStrategy]
    allowed_strategies: Set[LocatorStrategy]
    forbidden_strategies: Set[LocatorStrategy]
    syntax_guidelines: str
    verifier_constraints: str = ""


PLAYWRIGHT_PROFILE = FrameworkProfile(
    name="Playwright Python",
    locator_priority=[
        LocatorStrategy.test_id,
        LocatorStrategy.role,
        LocatorStrategy.label,
        LocatorStrategy.placeholder,
        LocatorStrategy.id,
        LocatorStrategy.name,
        LocatorStrategy.css,
        LocatorStrategy.xpath,
    ],
    allowed_strategies={
        LocatorStrategy.test_id,
        LocatorStrategy.role,
        LocatorStrategy.label,
        LocatorStrategy.placeholder,
        LocatorStrategy.id,
        LocatorStrategy.name,
        LocatorStrategy.css,
        LocatorStrategy.xpath,
    },
    forbidden_strategies={
        LocatorStrategy.class_name,
        LocatorStrategy.tag,
        LocatorStrategy.text,
    },
    syntax_guidelines=(
        "- Locator MUST be Playwright compatible.\n"
        "- Role locators must follow the format 'role|name' (e.g., 'button|Login').\n"
        "- Do not use class or tag strategies."
    ),
    verifier_constraints=(
        "Use fill('') to clear fields.\n"
        "Use get_by_role, get_by_test_id, get_by_label for locating elements.\n"
        "Use expect().to_be_visible(), expect().to_have_text() for assertions.\n"
        "All actions must use 'await'. Use locator.first for element references.\n"
        "Do not use keyboard.type() for regular input — use fill()."
    ),
)


CYPRESS_PROFILE = FrameworkProfile(
    name="Cypress Javascript",
    locator_priority=[
        LocatorStrategy.test_id,
        LocatorStrategy.id,
        LocatorStrategy.css,
        LocatorStrategy.name,
        LocatorStrategy.role,
        LocatorStrategy.xpath,
    ],
    allowed_strategies={
        LocatorStrategy.test_id,
        LocatorStrategy.id,
        LocatorStrategy.css,
        LocatorStrategy.name,
        LocatorStrategy.role,
        LocatorStrategy.xpath,
        LocatorStrategy.class_name,
        LocatorStrategy.tag,
        LocatorStrategy.text,
    },
    forbidden_strategies={
        LocatorStrategy.placeholder,
        LocatorStrategy.label,
    },
    syntax_guidelines=(
        "- Locator MUST be Cypress compatible (use standard web element attributes).\n"
        "- Test ID format: use css selectors like `[data-testid='...']`.\n"
        "- Do not use 'label' or 'placeholder' strategies."
    ),
    verifier_constraints=(
        "Use cy.get() with CSS selectors or cy.xpath() for locating elements.\n"
        "Use .should('be.visible') for visibility assertions.\n"
        "Use .clear() to clear fields, .type() to enter text.\n"
        "Use cy.url().should('include', '...') for URL assertions.\n"
        "Chain commands with . (dot notation). Do NOT use await — Cypress is synchronous.\n"
        "End statements with semicolons. Use JavaScript syntax, not Python."
    ),
)


SELENIUM_PROFILE = FrameworkProfile(
    name="Selenium Python",
    locator_priority=[
        LocatorStrategy.id,
        LocatorStrategy.name,
        LocatorStrategy.css,
        LocatorStrategy.xpath,
        LocatorStrategy.class_name,
        LocatorStrategy.tag,
    ],
    allowed_strategies={
        LocatorStrategy.id,
        LocatorStrategy.name,
        LocatorStrategy.css,
        LocatorStrategy.xpath,
        LocatorStrategy.class_name,
        LocatorStrategy.tag,
        LocatorStrategy.test_id,
    },
    forbidden_strategies={
        LocatorStrategy.role,
        LocatorStrategy.placeholder,
        LocatorStrategy.label,
        LocatorStrategy.text,
    },
    syntax_guidelines=(
        "- Locator MUST be Selenium By-compatible (e.g., By.ID, By.NAME, By.CSS_SELECTOR, By.XPATH, By.CLASS_NAME).\n"
        "- Role, placeholder, and label strategies are completely unsupported in Selenium."
    ),
    verifier_constraints=(
        "Use driver.find_element(By.X, 'value') to locate elements.\n"
        "Use element.is_displayed() for visibility checks.\n"
        "Use element.clear() to clear fields, element.send_keys() to type.\n"
        "Use WebDriverWait with expected_conditions for waits.\n"
        "Do NOT use await — Selenium is synchronous Python."
    ),
)


APPIUM_PROFILE = FrameworkProfile(
    name="Appium Python",
    locator_priority=[
        LocatorStrategy.test_id,  # maps to accessibility ID
        LocatorStrategy.id,       # maps to resource ID
        LocatorStrategy.uiautomator,
        LocatorStrategy.text,
        LocatorStrategy.xpath,
        LocatorStrategy.class_name,
    ],
    allowed_strategies={
        LocatorStrategy.test_id,
        LocatorStrategy.id,
        LocatorStrategy.uiautomator,
        LocatorStrategy.text,
        LocatorStrategy.xpath,
        LocatorStrategy.class_name,
    },
    forbidden_strategies={
        LocatorStrategy.role,
        LocatorStrategy.placeholder,
        LocatorStrategy.label,
        LocatorStrategy.css,
        LocatorStrategy.name,
    },
    syntax_guidelines=(
        "- Locator MUST be Appium mobile driver compatible (iOS or Android).\n"
        "- Accessibility IDs (extracted as test_id) and Native Resource IDs (extracted as id) are highly preferred.\n"
        "- Strictly avoid CSS, role, or web placeholder strategies because this is a mobile simulator environment."
    ),
    verifier_constraints=(
        "Use driver.find_element(AppiumBy.X, 'value') to locate elements.\n"
        "Use element.is_displayed() for visibility checks.\n"
        "Use element.clear() to clear fields, element.send_keys() to type.\n"
        "Use AppiumBy.ACCESSIBILITY_ID, AppiumBy.ID, AppiumBy.XPATH, AppiumBy.ANDROID_UIAUTOMATOR.\n"
        "Do NOT use await — Appium is synchronous Python."
    ),
)


def get_framework_profile(framework_name: str) -> FrameworkProfile:
    name_lower = framework_name.lower().strip()
    if name_lower == "playwright":
        return PLAYWRIGHT_PROFILE
    elif name_lower == "cypress":
        return CYPRESS_PROFILE
    elif name_lower == "selenium":
        return SELENIUM_PROFILE
    elif name_lower == "appium":
        return APPIUM_PROFILE
    else:
        raise ValueError(f"Unsupported framework profile: {framework_name}")

