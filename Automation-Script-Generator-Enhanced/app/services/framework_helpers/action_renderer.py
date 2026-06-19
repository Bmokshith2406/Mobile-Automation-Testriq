from typing import List, Optional
import re

from app.models.cir import (
    CIRAction,
    LocatorStrategy,
    ActionType,
    NavigateType,
    AssertionType,
    WaitCondition,
)
from app.utils.locator_utils import (
    escape_css_identifier,
    is_valid_xpath,
    VALID_ARIA_ROLES,
)
from app.core.config import get_settings

settings = get_settings()
EXPECT_TIMEOUT = settings.EXPECT_TIMEOUT_MS


class ActionRenderer:
    """
    Renders CIR actions into Playwright Python statements.
    """

    def _clean_role_name(self, name: str) -> str:
        name = name.strip()
        name = re.sub(r"^(name|aria-label|label)\s*=\s*", "", name, flags=re.I)
        name = name.strip("'\"")
        return name.strip()

    def _locator(self, action: CIRAction) -> str:
        strategy = action.target.locator_strategy
        value = action.target.locator_value

        if strategy == LocatorStrategy.placeholder:
            return f"page.get_by_placeholder({repr(value)})"

        if strategy == LocatorStrategy.label:
            return f"page.get_by_label({repr(value)})"

        if strategy == LocatorStrategy.text:
            raise RuntimeError(f"Semantic locator forbidden in generator: {strategy}")

        if strategy == LocatorStrategy.id:
            raise RuntimeError("ID strategy forbidden in generator. Must be CSS.")

        if strategy == LocatorStrategy.test_id:
            return f"page.get_by_test_id({repr(value)})"

        if strategy == LocatorStrategy.role:
            if "|" not in value:
                raise RuntimeError(f"Invalid role locator format: {value}")

            role, name = value.split("|", 1)
            role = role.strip().lower()
            name = self._clean_role_name(name)

            if not role or not name:
                raise RuntimeError(f"Invalid role locator (empty role or name): {value}")

            if role not in VALID_ARIA_ROLES:
                raise RuntimeError(f"Invalid ARIA role: {role}")

            if role == "link":
                return f"page.get_by_role('link', name={repr(name)})"

            # Buttons are safe + semantic → USE ROLE
            if role == "button":
                return f"page.get_by_role('button', name={repr(name)})"

            return f"page.get_by_role({repr(role)}, name={repr(name)})"

        # Auto-upgrade XPath buttons to role
        if strategy == LocatorStrategy.xpath:
            m_btn = re.search(r"//button\[(?:text\(\)|normalize-space\(\))\s*=\s*(['\"])(.*?)\1\]", value, re.I)
            if m_btn:
                return f"page.get_by_role('button', name={repr(m_btn.group(2))})"
            m_link = re.search(r"//a\[(?:text\(\)|normalize-space\(\))\s*=\s*(['\"])(.*?)\1\]", value, re.I)
            if m_link:
                return f"page.get_by_role('link', name={repr(m_link.group(2))})"

        # Auto-upgrade XPath headings to role=heading
        if strategy == LocatorStrategy.xpath:
            if re.search(r"//h[1-6]\[", value, re.I):
                m = re.search(r"normalize-space\(\)\s*=\s*(['\"])(.*?)\1", value)
                if m:
                    text = m.group(2)
                    return f"page.get_by_role('heading', name={repr(text)})"

        if strategy == LocatorStrategy.xpath:
            hardened = self._harden_xpath(value)
            return f"page.locator({repr(hardened)})"

        if strategy == LocatorStrategy.css:
            return f"page.locator({repr(value)})"

        raise RuntimeError(f"Unsupported locator strategy: {strategy}")

    def _harden_xpath(self, xpath: str) -> str:
        """
        Converts //tag[text()='X'] → //tag[normalize-space()='X']
        """
        m = re.search(r"text\(\)\s*=\s*(['\"])(.*?)\1", xpath)
        if not m:
            return xpath

        quote = m.group(1)
        text = m.group(2)
        safe = f"normalize-space()={quote}{text}{quote}"

        return re.sub(r"text\(\)\s*=\s*(['\"])(.*?)\1", safe, xpath)

    def _raw_selector(self, action: CIRAction) -> Optional[str]:
        if not action.target:
            return None

        if action.target.locator_strategy in {
            LocatorStrategy.role,
            LocatorStrategy.test_id,
            LocatorStrategy.xpath,
        }:
            return None

        return repr(action.target.locator_value)

    def render_action(self, action: CIRAction) -> List[str]:
        if action.action_type == ActionType.click:
            return self._generate_click(action)
        if action.action_type == ActionType.type:
            return self._generate_type(action)
        if action.action_type == ActionType.clear:
            return self._generate_clear(action)
        if action.action_type == ActionType.select:
            return self._generate_select(action)
        if action.action_type == ActionType.navigate:
            return self._generate_navigate(action)
        if action.action_type == ActionType.assert_action:
            return self._generate_assert(action)
        if action.action_type == ActionType.hover:
            return self._generate_hover(action)
        if action.action_type == ActionType.double_click:
            return self._generate_double_click(action)
        if action.action_type == ActionType.right_click:
            return self._generate_right_click(action)
        if action.action_type == ActionType.scroll:
            return self._generate_scroll(action)
        if action.action_type == ActionType.drag_drop:
            return self._generate_drag_drop(action)
        if action.action_type == ActionType.upload_file:
            return self._generate_upload_file(action)
        if action.action_type == ActionType.keyboard:
            return self._generate_keyboard(action)
        if action.action_type == ActionType.switch_frame:
            return self._generate_switch_frame(action)
        if action.action_type == ActionType.switch_window:
            return self._generate_switch_window(action)
        if action.action_type == ActionType.execute_script:
            return self._generate_execute_script(action)
        if action.action_type == ActionType.wait_for:
            return self._generate_wait_for(action)

        raise RuntimeError(f"Unsupported action type: {action.action_type}")

    def _generate_click(self, action: CIRAction) -> List[str]:
        loc = self._locator(action)
        return [
            f"locator = {loc}",
            "target = locator.first",
            f"await expect(target).to_be_visible(timeout={EXPECT_TIMEOUT})",
            "await target.click()",
        ]

    def _generate_clear(self, action: CIRAction) -> List[str]:
        if not action.target:
            raise RuntimeError("CLEAR action requires target")

        loc = self._locator(action)
        return [
            f"locator = {loc}",
            "target = locator.first",
            f"await expect(target).to_be_visible(timeout={EXPECT_TIMEOUT})",
            "await target.fill('')",
        ]

    def _generate_type(self, action: CIRAction) -> List[str]:
        lines = []

        if action.target:
            loc = self._locator(action)
            lines.extend([
                f"locator = {loc}",
                "target = locator.first",
                f"await expect(target).to_be_visible(timeout={EXPECT_TIMEOUT})",
            ])

        if action.value is not None:
            if not action.target:
                raise RuntimeError("TYPE with value requires target")
            lines.append(f"await target.fill({repr(action.value)})")

        return lines

    def _generate_select(self, action: CIRAction) -> List[str]:
        lines = []

        if action.target:
            loc = self._locator(action)
            lines.extend([
                f"locator = {loc}",
                "target = locator.first",
                f"await expect(target).to_be_visible(timeout={EXPECT_TIMEOUT})",
            ])

        if action.value is not None:
            raw = action.value
            mode = action.value_mode or "value"

            if mode == "index":
                lines.append(f"await target.select_option(index={int(raw)})")
            elif mode == "label":
                lines.append(f"await target.select_option(label={repr(raw)})")
            else:
                lines.append(f"await target.select_option({repr(raw)})")

        return lines

    def _generate_navigate(self, action: CIRAction) -> List[str]:
        if action.navigate_type == NavigateType.url:
            return [f"await page.goto({repr(action.value)}, wait_until='domcontentloaded')"]

        if action.navigate_type == NavigateType.back:
            return ["await page.go_back()"]

        if action.navigate_type == NavigateType.forward:
            return ["await page.go_forward()"]

        raise RuntimeError(f"Unsupported navigate type: {action.navigate_type}")

    def _generate_assert(self, action: CIRAction) -> List[str]:
        assertion = action.assertion
        lines: List[str] = []

        if action.target:
            loc = self._locator(action)
            lines.append(f"locator = {loc}")
            target = "locator.first"
        else:
            target = "page"

        val = assertion.expected_value
        lines.append("# [ASSERT]")

        if assertion.assert_type == AssertionType.text_equals:
            lines.append(
                f"await expect({target}).to_have_text({repr(val)}, timeout={EXPECT_TIMEOUT})"
            )

        elif assertion.assert_type == AssertionType.text_contains:
            lines.append(
                f"await expect({target}).to_contain_text({repr(val)}, timeout={EXPECT_TIMEOUT})"
            )

        elif assertion.assert_type == AssertionType.url_contains:
            pattern = re.escape(val)
            lines.append(
                f"await expect(page).to_have_url(re.compile(r'.*{pattern}.*'))"
            )

        elif assertion.assert_type == AssertionType.element_is_visible:
            lines.append(
                f"await expect({target}).to_be_visible(timeout={EXPECT_TIMEOUT})"
            )

        elif assertion.assert_type in {AssertionType.title_contains, AssertionType.title_equals}:
            pattern = re.escape(val or "")
            title_pattern = f"^{pattern}$" if assertion.assert_type == AssertionType.title_equals else f".*{pattern}.*"
            lines.append(
                f"await expect(page).to_have_title(re.compile(r'{title_pattern}'), timeout={EXPECT_TIMEOUT})"
            )

        else:
            raise RuntimeError(f"Unsupported assertion type: {assertion.assert_type}")

        return lines

    def _generate_hover(self, action: CIRAction) -> List[str]:
        loc = self._locator(action)
        return [
            f"locator = {loc}",
            "target = locator.first",
            f"await expect(target).to_be_visible(timeout={EXPECT_TIMEOUT})",
            "await target.hover()",
        ]

    def _generate_double_click(self, action: CIRAction) -> List[str]:
        loc = self._locator(action)
        return [
            f"locator = {loc}",
            "target = locator.first",
            f"await expect(target).to_be_visible(timeout={EXPECT_TIMEOUT})",
            "await target.dblclick()",
        ]

    def _generate_right_click(self, action: CIRAction) -> List[str]:
        loc = self._locator(action)
        return [
            f"locator = {loc}",
            "target = locator.first",
            f"await expect(target).to_be_visible(timeout={EXPECT_TIMEOUT})",
            "await target.click(button='right')",
        ]

    def _generate_scroll(self, action: CIRAction) -> List[str]:
        if action.target:
            loc = self._locator(action)
            return [
                f"locator = {loc}",
                "target = locator.first",
                "await target.scroll_into_view_if_needed()",
            ]
        direction = action.scroll_direction or "down"
        amount = action.scroll_amount or 500
        if direction == "down":
            return [f"await page.mouse.wheel(0, {amount})"]
        elif direction == "up":
            return [f"await page.mouse.wheel(0, -{amount})"]
        return [f"await page.mouse.wheel(0, {amount})"]

    def _generate_drag_drop(self, action: CIRAction) -> List[str]:
        source = self._locator(action)
        if action.drag_target:
            drag_action_copy = action.model_copy(update={"target": action.drag_target})
            target = self._locator(drag_action_copy)
            return [
                f"source = {source}",
                f"dest = {target}",
                "await source.drag_to(dest)",
            ]
        return [
            f"source = {source}",
            "await source.drag_to(source)",
        ]

    def _generate_upload_file(self, action: CIRAction) -> List[str]:
        loc = self._locator(action)
        path = repr(action.file_path_to_upload or "/path/to/file")
        return [
            f"locator = {loc}",
            "target = locator.first",
            f"await target.set_input_files({path})",
        ]

    def _generate_keyboard(self, action: CIRAction) -> List[str]:
        key = action.key_combination or "Tab"
        return [f"await page.keyboard.press({repr(key)})"]

    def _generate_switch_frame(self, action: CIRAction) -> List[str]:
        selector = action.frame_locator or "iframe"
        return [
            f"frame = page.frame_locator({repr(selector)})",
            "# Use 'frame' instead of 'page' for subsequent actions",
        ]

    def _generate_switch_window(self, action: CIRAction) -> List[str]:
        idx = action.window_index or 0
        return [
            "pages = context.pages",
            f"page = pages[{idx}] if len(pages) > {idx} else pages[-1]",
            "page.bring_to_front()",
        ]

    def _generate_execute_script(self, action: CIRAction) -> List[str]:
        expr = action.script_expression or "void(0)"
        return [f"await page.evaluate({repr(expr)})"]

    def _generate_wait_for(self, action: CIRAction) -> List[str]:
        condition = action.wait_for_condition or "load"
        timeout = (action.wait_for_timeout or 10) * 1000
        return [f"await page.wait_for_load_state({repr(condition)}, timeout={timeout})"]

    def generate_wait(self, action: CIRAction) -> List[str]:
        if not action.wait:
            return []

        timeout = action.wait.timeout * 1000

        if action.wait.condition == WaitCondition.url_contains:
            val = getattr(action.wait, "value", None)
            if not val and action.assertion:
                val = action.assertion.expected_value

            if not val:
                return []

            pattern = re.escape(val)
            return [
                f"await page.wait_for_url(re.compile(r'.*{pattern}.*'), timeout={timeout})"
            ]

        if action.assertion and action.assertion.assert_type in {
            AssertionType.title_contains,
            AssertionType.title_equals,
        }:
            return []

        selector = self._raw_selector(action)
        if not selector:
            return []

        return [f"await page.wait_for_selector({selector}, timeout={timeout}, state='visible')"]

