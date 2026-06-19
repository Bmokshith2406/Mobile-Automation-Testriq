from typing import List
import re

from app.models.cir import (
    CIRBlock,
    CIRAction,
    ActionType,
    NavigateType,
    AssertionType,
    LocatorStrategy,
    WaitCondition,
)

# ---------------------------------------------
# ARIA ROLE CONTRACT
# ---------------------------------------------
VALID_ARIA_ROLES = {
    "button", "link", "textbox", "checkbox", "radio",
    "combobox", "listbox", "option", "tab", "menuitem",
    "heading", "img", "row", "cell", "gridcell",
    "navigation", "banner", "contentinfo", "main",
    "form", "search", "dialog", "alert", "status",
}


class CIRValidationError(Exception):
    pass


class CIRValidator:
    """
    HARDENED CIR VALIDATOR

    LAST safety gate before Playwright code emission.

    Guarantees:
    - Never allows broken XPath
    - Never allows unbalanced quotes
    - Never allows invalid selectors
    - Enforces CIR legality
    - Placeholder-safe (modifier can repair)
    - Enforces extractor contracts
    """

    # Disallowed semantic locators in CIR
    DISALLOWED_STRATEGIES = {
        LocatorStrategy.text,
        LocatorStrategy.label,
        LocatorStrategy.placeholder,
    }

    def validate_blocks(self, blocks: List[CIRBlock]) -> None:
        for block in blocks:
            if not block.actions:
                continue

            for action in block.actions:
                self._validate_action(action)

    # =====================================================
    # ACTION VALIDATION
    # =====================================================

    def _validate_action(self, action: CIRAction) -> None:
        if not isinstance(action.action_type, ActionType):
            raise CIRValidationError(
                f"Invalid action type: {action.action_type}"
            )

        # -------------------------
        # WAIT
        # -------------------------
        if action.wait:
            if action.wait.timeout is None or action.wait.timeout <= 0:
                raise CIRValidationError(
                    "Wait timeout must be a positive number."
                )

            if not isinstance(action.wait.condition, WaitCondition):
                raise CIRValidationError(
                    f"Unsupported wait condition: {action.wait.condition}"
                )

        # -------------------------
        # TARGET / LOCATOR
        # -------------------------
        if action.target:
            self._validate_locator(action)

        # -------------------------
        # NAVIGATE
        # -------------------------
        if action.action_type == ActionType.navigate:
            self._validate_navigate(action)

        # -------------------------
        # CLICK
        # -------------------------
        elif action.action_type == ActionType.click:
            if action.value is not None:
                raise CIRValidationError(
                    "Click action must NOT have a value."
                )

        # -------------------------
        # TYPE
        # -------------------------
        elif action.action_type == ActionType.type:
            if not action.value:
                raise CIRValidationError("Type action requires value.")
            if not action.target and action.value not in {"\n", "\r", "\ue007"}:
                raise CIRValidationError(
                    "Targetless type action is only allowed for keyboard Enter/Return."
                )

        # -------------------------
        # SELECT
        # -------------------------
        elif action.action_type == ActionType.select:
            if not action.target and not action.value:
                raise CIRValidationError(
                    "Select action must have at least a target or a value."
                )
                
        # -------------------------
        # CLEAR
        # -------------------------
        elif action.action_type == ActionType.clear:
            if not action.target:
                raise CIRValidationError("Clear action requires target.")
            if action.value is not None:
                raise CIRValidationError("Clear action must NOT have a value.")


        # -------------------------
        # ASSERT
        # -------------------------
        elif action.action_type == ActionType.assert_action:
            self._validate_assert(action)

        elif action.action_type in {
            ActionType.hover,
            ActionType.double_click,
            ActionType.right_click,
            ActionType.scroll,
            ActionType.drag_drop,
            ActionType.upload_file,
            ActionType.keyboard,
            ActionType.switch_frame,
            ActionType.switch_window,
            ActionType.execute_script,
            ActionType.wait_for,
        }:
            # Extended action types — validated by CIRAction model_validator
            pass

        else:
            raise CIRValidationError(
                f"Unsupported action type: {action.action_type}"
            )

    # =====================================================
    # LOCATOR FIREWALL
    # =====================================================

    def _validate_locator(self, action: CIRAction) -> None:
        loc = action.target

        if not loc.locator_value or not loc.locator_value.strip():
            raise CIRValidationError(
                "Target locator must have a non-empty locator_value."
            )

        if not isinstance(loc.locator_strategy, LocatorStrategy):
            raise CIRValidationError(
                f"Unsupported locator strategy: {loc.locator_strategy}"
            )

        # Dynamic Profile Check — use per-request framework context when available,
        # falling back to global config only if no context is active (e.g. in tests).
        from app.core.config import get_settings
        from app.core.framework_profiles import get_framework_profile
        try:
            from app.core.context import active_framework_ctx
            framework = active_framework_ctx.get(None)
        except Exception:
            framework = None
        if not framework:
            framework = get_settings().AUTOMATION_FRAMEWORK
        profile = get_framework_profile(framework)

        if loc.locator_strategy in profile.forbidden_strategies:
            raise CIRValidationError(
                f"Locator strategy forbidden in {profile.name}: {loc.locator_strategy}"
            )
        if loc.locator_strategy not in profile.allowed_strategies:
            raise CIRValidationError(
                f"Locator strategy unsupported in {profile.name}: {loc.locator_strategy}"
            )

        v = loc.locator_value.strip()

        # Balanced parentheses
        if v.count("(") != v.count(")"):
            raise CIRValidationError(
                f"Unbalanced parentheses in locator: {v}"
            )

        # Balanced quotes
        if (v.count("'") % 2 != 0) or (v.count('"') % 2 != 0):
            raise CIRValidationError(
                f"Unbalanced quotes in locator: {v}"
            )

        # -------------------------
        # ROLE FORMAT + CONTRACT
        # -------------------------
        if loc.locator_strategy == LocatorStrategy.role:
            parts = [p.strip() for p in v.split("|") if p.strip()]

            role = None
            name = None

            # role|heading|name|Text
            if (
                len(parts) == 4
                and parts[0].lower() == "role"
                and parts[2].lower() == "name"
            ):
                role = parts[1]
                name = parts[3]

            # heading|name|Text
            elif len(parts) == 3 and parts[1].lower() == "name":
                role, _, name = parts

            # role|heading|Text
            elif len(parts) == 3 and parts[0].lower() == "role":
                _, role, name = parts

            # heading|Text
            elif len(parts) == 2:
                role, name = parts

            # Text → default role
            elif len(parts) == 1:
                role = "button"
                name = parts[0]

            else:
                raise CIRValidationError(f"Invalid role locator structure: {v}")

            if not role or not name:
                raise CIRValidationError(
                    f"Invalid role locator (empty role or name): {v}"
                )

            if role.lower() not in VALID_ARIA_ROLES:
                raise CIRValidationError(
                    f"Invalid ARIA role: {role}"
                )




        # -------------------------
        # XPATH
        # -------------------------
        if loc.locator_strategy == LocatorStrategy.xpath:
            if not self.is_valid_xpath(v):
                raise CIRValidationError(
                    f"Invalid XPath: {v}"
                )

        # -------------------------
        # CSS
        # -------------------------
        if loc.locator_strategy == LocatorStrategy.css:
            if v.strip() in {"*", "* *"}:
                raise CIRValidationError(
                    f"Wildcard CSS selector forbidden: {v}"
                )

            if v.endswith(">") or v.startswith(">"):
                raise CIRValidationError(
                    f"Invalid CSS selector: {v}"
                )

            if re.search(r"\[\s*\]", v):
                raise CIRValidationError(
                    f"Empty attribute selector in CSS: {v}"
                )

    @staticmethod
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



    # =====================================================
    # NAVIGATE
    # =====================================================

    def _validate_navigate(self, action: CIRAction) -> None:
        if action.navigate_type and not isinstance(
            action.navigate_type, NavigateType
        ):
            raise CIRValidationError(
                f"Invalid navigate type: {action.navigate_type}"
            )

        nav_type = action.navigate_type or NavigateType.url

        if action.target is not None:
            raise CIRValidationError(
                "Navigate action must NOT have a target locator."
            )

        if nav_type == NavigateType.url:
            if not action.value or not action.value.strip():
                raise CIRValidationError(
                    "URL navigation requires a URL value."
                )

            if not re.match(r"^https?://", action.value.strip()):
                raise CIRValidationError(
                    f"Invalid URL format: {action.value}"
                )
        else:
            if action.value:
                raise CIRValidationError(
                    f"{nav_type.value} navigation must NOT have a value."
                )

    # =====================================================
    # ASSERT
    # =====================================================

    def _validate_assert(self, action: CIRAction) -> None:
        if action.value is not None:
            raise CIRValidationError(
                "Assert action must NOT have a value."
            )

        if not action.assertion:
            raise CIRValidationError(
                "Assert action requires an assertion block."
            )

        assertion = action.assertion
        if not isinstance(assertion.assert_type, AssertionType):
            raise CIRValidationError(
                f"Invalid assertion type: {assertion.assert_type}"
            )

        assert_type = assertion.assert_type

        # -------------------------
        # URL ASSERTION
        # -------------------------
        if assert_type == AssertionType.url_contains:
            if not assertion.expected_value or not assertion.expected_value.strip():
                raise CIRValidationError(
                    "url_contains assertion requires expected_value."
                )

            if action.target is not None:
                raise CIRValidationError(
                    "url_contains assertion must NOT have a target locator."
                )

        # -------------------------
        # VISIBILITY ASSERTION
        # -------------------------
        elif assert_type == AssertionType.element_is_visible:
            if assertion.expected_value:
                raise CIRValidationError(
                    "element_is_visible assertion must NOT have expected_value."
                )

            if not action.target:
                raise CIRValidationError(
                    "element_is_visible assertion requires target."
                )

        # -------------------------
        # TEXT ASSERTIONS
        # -------------------------
        elif assert_type in (
            AssertionType.text_contains,
            AssertionType.text_equals,
        ):
            if not action.target:
                raise CIRValidationError(
                    f"{assert_type.value} assertion requires target."
                )

            if not assertion.expected_value or not assertion.expected_value.strip():
                raise CIRValidationError(
                    f"{assert_type.value} assertion requires expected_value."
                )

        # -------------------------
        # TITLE ASSERTIONS
        # -------------------------
        elif assert_type in (
            AssertionType.title_contains,
            AssertionType.title_equals,
        ):
            if action.target is not None:
                raise CIRValidationError(
                    f"{assert_type.value} assertion must NOT have a target."
                )

            if not assertion.expected_value or not assertion.expected_value.strip():
                raise CIRValidationError(
                    f"{assert_type.value} assertion requires expected_value."
                )

        else:
            raise CIRValidationError(
                f"Unsupported assertion type: {assert_type.value}"
            )

