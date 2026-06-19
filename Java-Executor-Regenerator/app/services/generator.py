# app/services/step_code_generator.py

from typing import List, Optional
import json
import re

from app.models.cir import (
    CIRAction,
    ActionType,
    NavigateType,
    AssertionType,
    LocatorStrategy,
    DialogAction,
    WaitCondition,
)

EXPECT_TIMEOUT = 5000


class StepCodeGenerator:
    """
    Deterministic framework-aware step-body renderer.

    This mirrors the Automation-Script-Generator-Enhanced framework renderers
    closely enough for repaired step bodies to stay compatible with generated
    scripts, while remaining local to Executor-Regenerator.

    Supports all 17 ActionTypes and 16 AssertionTypes from the Enhanced edition.
    """

    def generate(
        self,
        action: CIRAction,
        *,
        original_lines: Optional[List[str]] = None,
        framework: str = "playwright",
    ) -> List[str]:
        if not isinstance(action, CIRAction):
            raise RuntimeError("Invalid CIRAction")

        framework = (framework or "playwright").strip().lower()

        match action.action_type:
            case ActionType.click:
                return self._click(action, framework=framework)
            case ActionType.type:
                return self._type(action, framework=framework)
            case ActionType.select:
                return self._select(action, framework=framework)
            case ActionType.navigate:
                return self._navigate(action, framework=framework)
            case ActionType.assert_action:
                return self._assert(action, framework=framework)
            case ActionType.handle_dialog:
                return self._handle_dialog(
                    action,
                    original_lines=original_lines or [],
                    framework=framework,
                )
            case ActionType.hover:
                return self._hover(action, framework=framework)
            case ActionType.double_click:
                return self._double_click(action, framework=framework)
            case ActionType.right_click:
                return self._right_click(action, framework=framework)
            case ActionType.scroll:
                return self._scroll(action, framework=framework)
            case ActionType.drag_drop:
                return self._drag_drop(action, framework=framework)
            case ActionType.upload_file:
                return self._upload_file(action, framework=framework)
            case ActionType.keyboard:
                return self._keyboard(action, framework=framework)
            case ActionType.switch_frame:
                return self._switch_frame(action, framework=framework)
            case ActionType.switch_window:
                return self._switch_window(action, framework=framework)
            case ActionType.execute_script:
                return self._execute_script(action, framework=framework)
            case ActionType.wait_for:
                return self._wait_for(action, framework=framework)

        raise RuntimeError(f"Unsupported action type: {action.action_type}")

    # ==================================================
    # ORIGINAL ACTION RENDERERS
    # ==================================================

    def _click(self, action: CIRAction, *, framework: str) -> List[str]:
        self._require_target(action, "CLICK")

        if framework == "cypress":
            return [f"{self._locator(action, framework=framework)}.should('be.visible').click();"]

        loc = self._locator(action, framework=framework)
        if framework == "playwright":
            return [
                f"locator = {loc}",
                "target = locator.first",
                f"await expect(target).to_be_visible(timeout={EXPECT_TIMEOUT})",
                "await target.click()",
            ]

        if framework in {"selenium", "appium"}:
            return [
                f"element = {loc}",
                "element.click()",
            ]

        raise RuntimeError(f"Unsupported framework: {framework}")

    def _type(self, action: CIRAction, *, framework: str) -> List[str]:
        if action.value is None:
            raise RuntimeError("TYPE action missing value")

        value = str(action.value)
        if not action.target:
            if framework == "playwright":
                return [f"await page.keyboard.type({repr(value)})"]
            if framework == "selenium":
                return [f"driver.switch_to.active_element.send_keys({repr(value)})"]
            if framework == "appium":
                return self._appium_targetless_type(value)
            if framework == "cypress":
                return [f"cy.focused().type({self._js_string(value)});"]
            raise RuntimeError(f"Unsupported framework: {framework}")

        if framework == "cypress":
            return [f"{self._locator(action, framework=framework)}.should('be.visible').type({self._js_string(value)});"]

        loc = self._locator(action, framework=framework)
        if framework == "playwright":
            return [
                f"locator = {loc}",
                "target = locator.first",
                f"await expect(target).to_be_visible(timeout={EXPECT_TIMEOUT})",
                f"await target.fill({repr(value)})",
            ]

        if framework in {"selenium", "appium"}:
            return [
                f"element = {loc}",
                f"element.send_keys({repr(value)})",
            ]

        raise RuntimeError(f"Unsupported framework: {framework}")

    def _select(self, action: CIRAction, *, framework: str) -> List[str]:
        self._require_target(action, "SELECT")

        if action.value is None:
            raise RuntimeError("SELECT action missing value")

        value = str(action.value)

        if framework == "cypress":
            return [f"{self._locator(action, framework=framework)}.should('be.visible').select({self._js_string(value)});"]

        loc = self._locator(action, framework=framework)
        if framework == "playwright":
            return [
                f"locator = {loc}",
                "target = locator.first",
                f"await expect(target).to_be_visible(timeout={EXPECT_TIMEOUT})",
                f"await target.select_option({repr(value)})",
            ]

        if framework == "selenium":
            return [
                f"select = Select({loc})",
                f"select.select_by_visible_text({repr(value)})",
            ]

        if framework == "appium":
            literal = self._xpath_literal(value)
            option_xpath = f"//*[@text={literal} or @content-desc={literal}]"
            return [
                f"element = {loc}",
                "element.click()",
                f"option = driver.find_element(AppiumBy.XPATH, {repr(option_xpath)})",
                "option.click()",
            ]

        raise RuntimeError(f"Unsupported framework: {framework}")

    def _navigate(self, action: CIRAction, *, framework: str) -> List[str]:
        nav_type = action.navigate_type or NavigateType.url

        if nav_type == NavigateType.url:
            if not action.value:
                raise RuntimeError("Navigate URL missing")
            if framework == "playwright":
                return [f"await page.goto({repr(str(action.value))}, wait_until='domcontentloaded')"]
            if framework in {"selenium", "appium"}:
                return [f"driver.get({repr(str(action.value))})"]
            if framework == "cypress":
                return [f"cy.visit({self._js_string(action.value)});"]

        if nav_type == NavigateType.back:
            if framework == "playwright":
                return ["await page.go_back()"]
            if framework in {"selenium", "appium"}:
                return ["driver.back()"]
            if framework == "cypress":
                return ["cy.go('back');"]

        if nav_type == NavigateType.forward:
            if framework == "playwright":
                return ["await page.go_forward()"]
            if framework in {"selenium", "appium"}:
                return ["driver.forward()"]
            if framework == "cypress":
                return ["cy.go('forward');"]

        if framework == "playwright":
            return ["await page.reload()"]
        if framework in {"selenium", "appium"}:
            return ["driver.refresh()"]
        if framework == "cypress":
            return ["cy.reload();"]

        raise RuntimeError(f"Unsupported framework: {framework}")

    def _assert(self, action: CIRAction, *, framework: str) -> List[str]:
        assertion = action.assertion
        if not assertion:
            raise RuntimeError("ASSERT action missing assertion block")

        if framework == "cypress":
            return self._assert_cypress(action)
        if framework in {"selenium", "appium"}:
            return self._assert_driver(action, framework=framework)

        lines: List[str] = ["# [ASSERT]"]
        if action.target:
            loc = self._locator(action, framework=framework)
            lines.extend([
                f"locator = {loc}",
                "target = locator.first",
            ])
            target = "target"
        else:
            target = "page"

        val = assertion.expected_value
        attr = action.attribute_name or "class"
        count = action.expected_count or 0

        match assertion.assert_type:
            case AssertionType.text_equals:
                lines.append(f"await expect({target}).to_have_text({repr(str(val))}, timeout={EXPECT_TIMEOUT})")
            case AssertionType.text_contains:
                lines.append(f"await expect({target}).to_contain_text({repr(str(val))}, timeout={EXPECT_TIMEOUT})")
            case AssertionType.url_contains:
                pattern = re.escape(str(val))
                lines.append(f"await expect(page).to_have_url(r'.*{pattern}.*')")
            case AssertionType.element_is_visible:
                lines.append(f"await expect({target}).to_be_visible(timeout={EXPECT_TIMEOUT})")
            case AssertionType.title_equals:
                lines.append(f"await expect(page).to_have_title({repr(str(val))}, timeout={EXPECT_TIMEOUT})")
            case AssertionType.title_contains:
                lines.append(f"await expect(page).to_have_title(re.compile(r'.*{re.escape(str(val))}.*'), timeout={EXPECT_TIMEOUT})")
            case AssertionType.attribute_equals:
                lines.append(f"await expect({target}).to_have_attribute({repr(attr)}, {repr(str(val))}, timeout={EXPECT_TIMEOUT})")
            case AssertionType.attribute_contains:
                lines.append(f"attr_val = await {target}.get_attribute({repr(attr)})")
                lines.append(f"assert {repr(str(val))} in (attr_val or '')")
            case AssertionType.element_count:
                lines.append(f"await expect({target}).to_have_count({count}, timeout={EXPECT_TIMEOUT})")
            case AssertionType.element_enabled:
                lines.append(f"await expect({target}).to_be_enabled(timeout={EXPECT_TIMEOUT})")
            case AssertionType.element_disabled:
                lines.append(f"await expect({target}).to_be_disabled(timeout={EXPECT_TIMEOUT})")
            case AssertionType.element_checked:
                lines.append(f"await expect({target}).to_be_checked(timeout={EXPECT_TIMEOUT})")
            case AssertionType.element_unchecked:
                lines.append(f"await expect({target}).not_to_be_checked(timeout={EXPECT_TIMEOUT})")
            case AssertionType.element_value:
                lines.append(f"await expect({target}).to_have_value({repr(str(val))}, timeout={EXPECT_TIMEOUT})")
            case AssertionType.list_contains:
                lines.append(f"await expect({target}).to_contain_text({repr(str(val))}, timeout={EXPECT_TIMEOUT})")
            case AssertionType.page_source_contains:
                lines.append("page_content = await page.content()")
                lines.append(f"assert {repr(str(val))} in page_content")
            case _:
                raise RuntimeError(f"Unsupported assertion type: {assertion.assert_type}")

        return lines

    def _handle_dialog(
        self,
        action: CIRAction,
        *,
        original_lines: List[str],
        framework: str,
    ) -> List[str]:
        if not action.dialog:
            raise RuntimeError("HANDLE_DIALOG action missing dialog block")

        dialog = action.dialog
        fallback_lines: List[str] = []

        if dialog.target is None:
            if framework == "playwright":
                if dialog.action == DialogAction.accept:
                    fallback_lines.append("page.once('dialog', lambda d: d.accept())")
                else:
                    fallback_lines.append("page.once('dialog', lambda d: d.dismiss())")
            elif framework in {"selenium", "appium"}:
                fallback_lines.append("alert = driver.switch_to.alert")
                fallback_lines.append("alert.accept()" if dialog.action == DialogAction.accept else "alert.dismiss()")
            elif framework == "cypress":
                fallback_lines.append("cy.on('window:confirm', () => true);" if dialog.action == DialogAction.accept else "cy.on('window:confirm', () => false);")
            else:
                raise RuntimeError(f"Unsupported framework: {framework}")

            return [*fallback_lines, *original_lines]

        click_action = CIRAction(action_type=ActionType.click, target=dialog.target)
        return [*self._click(click_action, framework=framework), *original_lines]

    # ==================================================
    # ENHANCED: 11 NEW ACTION RENDERERS
    # ==================================================

    def _hover(self, action: CIRAction, *, framework: str) -> List[str]:
        self._require_target(action, "HOVER")
        loc = self._locator(action, framework=framework)

        if framework == "playwright":
            return [
                f"locator = {loc}",
                "target = locator.first",
                f"await expect(target).to_be_visible(timeout={EXPECT_TIMEOUT})",
                "await target.hover()",
            ]
        if framework == "selenium":
            return [
                f"element = {loc}",
                "ActionChains(driver).move_to_element(element).perform()",
            ]
        if framework == "appium":
            return [
                f"element = {loc}",
                "driver.execute_script('mobile: swipe', {'element': element.id, 'direction': 'up'})",
            ]
        if framework == "cypress":
            return [f"{loc}.trigger('mouseover');"]

        raise RuntimeError(f"Unsupported framework: {framework}")

    def _double_click(self, action: CIRAction, *, framework: str) -> List[str]:
        self._require_target(action, "DOUBLE_CLICK")
        loc = self._locator(action, framework=framework)

        if framework == "playwright":
            return [
                f"locator = {loc}",
                "target = locator.first",
                f"await expect(target).to_be_visible(timeout={EXPECT_TIMEOUT})",
                "await target.dbl_click()",
            ]
        if framework == "selenium":
            return [
                f"element = {loc}",
                "ActionChains(driver).double_click(element).perform()",
            ]
        if framework == "appium":
            return [
                f"element = {loc}",
                "element.click()",
                "element.click()",
            ]
        if framework == "cypress":
            return [f"{loc}.dblclick();"]

        raise RuntimeError(f"Unsupported framework: {framework}")

    def _right_click(self, action: CIRAction, *, framework: str) -> List[str]:
        self._require_target(action, "RIGHT_CLICK")
        loc = self._locator(action, framework=framework)

        if framework == "playwright":
            return [
                f"locator = {loc}",
                "target = locator.first",
                f"await expect(target).to_be_visible(timeout={EXPECT_TIMEOUT})",
                "await target.click(button='right')",
            ]
        if framework == "selenium":
            return [
                f"element = {loc}",
                "ActionChains(driver).context_click(element).perform()",
            ]
        if framework == "appium":
            return [
                f"element = {loc}",
                "driver.execute_script('mobile: longClick', {'element': element.id})",
            ]
        if framework == "cypress":
            return [f"{loc}.rightclick();"]

        raise RuntimeError(f"Unsupported framework: {framework}")

    def _scroll(self, action: CIRAction, *, framework: str) -> List[str]:
        direction = (action.scroll_direction or "down").lower()
        amount = action.scroll_amount or 300
        delta_y = amount if direction == "down" else -amount if direction == "up" else 0
        delta_x = amount if direction == "right" else -amount if direction == "left" else 0

        if framework == "playwright":
            if action.target:
                loc = self._locator(action, framework=framework)
                return [
                    f"locator = {loc}",
                    "await locator.first.scroll_into_view_if_needed()",
                ]
            return [f"await page.mouse.wheel({delta_x}, {delta_y})"]

        if framework == "selenium":
            return [f"driver.execute_script('window.scrollBy({delta_x}, {delta_y})')"]

        if framework == "appium":
            appium_dir = "up" if direction == "up" else "down"
            return [f"driver.execute_script('mobile: scroll', {{'direction': {repr(appium_dir)}}})"]

        if framework == "cypress":
            if direction in {"up", "down"}:
                pos = "bottom" if direction == "down" else "top"
                return [f"cy.scrollTo('{pos}');"]
            return [f"cy.scrollTo('{direction}');"]

        raise RuntimeError(f"Unsupported framework: {framework}")

    def _drag_drop(self, action: CIRAction, *, framework: str) -> List[str]:
        self._require_target(action, "DRAG_DROP")
        src_loc = self._locator(action, framework=framework)

        if framework == "playwright":
            if action.drag_target:
                tgt_action = CIRAction(action_type=ActionType.click, target=action.drag_target)
                tgt_loc = self._locator(tgt_action, framework=framework)
                return [
                    f"source = {src_loc}",
                    f"target_el = {tgt_loc}",
                    "await source.first.drag_to(target_el.first)",
                ]
            return [
                f"source = {src_loc}",
                "await source.first.drag_to(page.locator('body'))",
            ]

        if framework == "selenium":
            if action.drag_target:
                tgt_action = CIRAction(action_type=ActionType.click, target=action.drag_target)
                tgt_loc = self._locator(tgt_action, framework=framework)
                return [
                    f"source = {src_loc}",
                    f"target_el = {tgt_loc}",
                    "ActionChains(driver).drag_and_drop(source, target_el).perform()",
                ]
            return [
                f"source = {src_loc}",
                "ActionChains(driver).click_and_hold(source).move_by_offset(100, 0).release().perform()",
            ]

        if framework == "appium":
            return [
                f"source = {src_loc}",
                "driver.execute_script('mobile: dragFromToForDuration', {'fromElement': source.id, 'toElement': source.id, 'duration': 1.0})",
            ]

        if framework == "cypress":
            return [f"{src_loc}.drag({{ release: true }});"]

        raise RuntimeError(f"Unsupported framework: {framework}")

    def _upload_file(self, action: CIRAction, *, framework: str) -> List[str]:
        file_path = action.file_path_to_upload or "/tmp/upload_file"

        if framework == "playwright":
            if action.target:
                loc = self._locator(action, framework=framework)
                return [
                    f"locator = {loc}",
                    f"await locator.first.set_input_files({repr(file_path)})",
                ]
            return [f"await page.set_input_files('input[type=\"file\"]', {repr(file_path)})"]

        if framework in {"selenium", "appium"}:
            if action.target:
                loc = self._locator(action, framework=framework)
                return [
                    f"element = {loc}",
                    f"element.send_keys({repr(file_path)})",
                ]
            return [
                "element = driver.find_element(By.CSS_SELECTOR, 'input[type=\"file\"]')",
                f"element.send_keys({repr(file_path)})",
            ]

        if framework == "cypress":
            if action.target:
                loc = self._locator(action, framework=framework)
                return [f"{loc}.selectFile({self._js_string(file_path)});"]
            return [f"cy.get('input[type=\"file\"]').selectFile({self._js_string(file_path)});"]

        raise RuntimeError(f"Unsupported framework: {framework}")

    def _keyboard(self, action: CIRAction, *, framework: str) -> List[str]:
        combo = action.key_combination or ""

        if framework == "playwright":
            return [f"await page.keyboard.press({repr(combo)})"]

        if framework == "selenium":
            parts = combo.split("+")
            modifier_map = {
                "control": "Keys.CONTROL", "shift": "Keys.SHIFT", "alt": "Keys.ALT",
                "meta": "Keys.META", "enter": "Keys.ENTER", "tab": "Keys.TAB",
                "escape": "Keys.ESCAPE", "backspace": "Keys.BACK_SPACE",
                "delete": "Keys.DELETE", "home": "Keys.HOME", "end": "Keys.END",
            }
            key_expr = " + ".join(
                modifier_map.get(p.lower(), repr(p)) for p in parts
            )
            return [
                "active = driver.switch_to.active_element",
                f"active.send_keys({key_expr})",
            ]

        if framework == "appium":
            keycode_map = {
                "enter": "66", "tab": "61", "escape": "111", "backspace": "67",
                "delete": "112", "home": "122", "end": "123",
            }
            keycode = keycode_map.get(combo.lower(), "66")
            return [f"driver.press_keycode({keycode})"]

        if framework == "cypress":
            return [f"cy.focused().type('{{{combo.lower()}}}');"]

        raise RuntimeError(f"Unsupported framework: {framework}")

    def _switch_frame(self, action: CIRAction, *, framework: str) -> List[str]:
        frame_sel = action.frame_locator or "iframe"

        if framework == "playwright":
            return [f"frame_locator = page.frame_locator({repr(frame_sel)})"]

        if framework in {"selenium", "appium"}:
            if action.target:
                loc = self._locator(action, framework=framework)
                return [
                    f"frame_el = {loc}",
                    "driver.switch_to.frame(frame_el)",
                ]
            return [f"driver.switch_to.frame(driver.find_element(By.CSS_SELECTOR, {repr(frame_sel)}))"]

        if framework == "cypress":
            return [
                f"cy.frameLoaded({self._js_string(frame_sel)})",
                f"cy.iframe({self._js_string(frame_sel)})",
            ]

        raise RuntimeError(f"Unsupported framework: {framework}")

    def _switch_window(self, action: CIRAction, *, framework: str) -> List[str]:
        idx = action.window_index or 1

        if framework == "playwright":
            return [
                "all_pages = context.pages",
                f"page = all_pages[{idx}] if len(all_pages) > {idx} else all_pages[-1]",
            ]

        if framework in {"selenium", "appium"}:
            return [
                "handles = driver.window_handles",
                f"driver.switch_to.window(handles[{idx}] if len(handles) > {idx} else handles[-1])",
            ]

        if framework == "cypress":
            return [f"// Cypress manages windows via cy.window(); switch to tab index {idx}"]

        raise RuntimeError(f"Unsupported framework: {framework}")

    def _execute_script(self, action: CIRAction, *, framework: str) -> List[str]:
        expr = action.script_expression or "undefined"

        if framework == "playwright":
            return [f"await page.evaluate({repr(expr)})"]

        if framework in {"selenium", "appium"}:
            return [f"driver.execute_script({repr(expr)})"]

        if framework == "cypress":
            return [f"cy.window().then((win) => win.eval({self._js_string(expr)}));"]

        raise RuntimeError(f"Unsupported framework: {framework}")

    def _wait_for(self, action: CIRAction, *, framework: str) -> List[str]:
        condition = action.wait_for_condition or WaitCondition.visible
        timeout_ms = (action.wait_for_timeout or 15) * 1000
        timeout_s = action.wait_for_timeout or 15

        if framework == "playwright":
            match condition:
                case WaitCondition.url_contains:
                    val = action.value or ""
                    return [f"await page.wait_for_url(r'.*{re.escape(val)}.*', timeout={timeout_ms})"]
                case WaitCondition.load_state | WaitCondition.network_idle:
                    return [f"await page.wait_for_load_state('networkidle', timeout={timeout_ms})"]
                case WaitCondition.hidden:
                    if action.target:
                        loc = self._locator(action, framework=framework)
                        return [f"await {loc}.first.wait_for(state='hidden', timeout={timeout_ms})"]
                    return [f"await page.wait_for_timeout({timeout_ms})"]
                case _:
                    if action.target:
                        loc = self._locator(action, framework=framework)
                        return [f"await {loc}.first.wait_for(state='visible', timeout={timeout_ms})"]
                    return [f"await page.wait_for_timeout({timeout_ms})"]

        if framework in {"selenium", "appium"}:
            match condition:
                case WaitCondition.url_contains:
                    val = action.value or ""
                    return [f"WebDriverWait(driver, {timeout_s}).until(EC.url_contains({repr(val)}))"]
                case _:
                    return [f"import time; time.sleep({timeout_s})"]

        if framework == "cypress":
            if action.target:
                loc = self._locator(action, framework=framework)
                return [f"{loc}.should('be.visible', {{ timeout: {timeout_ms} }});"]
            return [f"cy.wait({timeout_ms});"]

        raise RuntimeError(f"Unsupported framework: {framework}")

    # ==================================================
    # FRAMEWORK-SPECIFIC ASSERTIONS
    # ==================================================

    def _assert_driver(self, action: CIRAction, *, framework: str) -> List[str]:
        assertion = action.assertion
        if not assertion:
            raise RuntimeError("ASSERT action missing assertion block")

        lines: List[str] = ["# [ASSERT]"]
        val = assertion.expected_value
        attr = action.attribute_name or "class"

        if assertion.assert_type == AssertionType.url_contains:
            lines.append(f"assert {repr(str(val))} in driver.current_url")
            return lines

        if assertion.assert_type == AssertionType.title_equals:
            lines.append(f"assert driver.title == {repr(str(val))}")
            return lines

        if assertion.assert_type == AssertionType.title_contains:
            lines.append(f"assert {repr(str(val))} in driver.title")
            return lines

        if assertion.assert_type == AssertionType.page_source_contains:
            lines.append(f"assert {repr(str(val))} in driver.page_source")
            return lines

        if not action.target:
            raise RuntimeError("Driver assertion missing target locator")

        lines.append(f"element = {self._locator(action, framework=framework)}")

        match assertion.assert_type:
            case AssertionType.text_equals:
                lines.append(f"assert element.text == {repr(str(val))}")
            case AssertionType.text_contains:
                lines.append(f"assert {repr(str(val))} in element.text")
            case AssertionType.element_is_visible:
                lines.append("assert element.is_displayed()")
            case AssertionType.element_enabled:
                lines.append("assert element.is_enabled()")
            case AssertionType.element_disabled:
                lines.append("assert not element.is_enabled()")
            case AssertionType.element_checked:
                lines.append("assert element.is_selected()")
            case AssertionType.element_unchecked:
                lines.append("assert not element.is_selected()")
            case AssertionType.attribute_equals:
                lines.append(f"assert element.get_attribute({repr(attr)}) == {repr(str(val))}")
            case AssertionType.attribute_contains:
                lines.append(f"assert {repr(str(val))} in (element.get_attribute({repr(attr)}) or '')")
            case AssertionType.element_value:
                lines.append(f"assert element.get_attribute('value') == {repr(str(val))}")
            case AssertionType.element_count:
                count = action.expected_count or 0
                loc_val = repr(action.target.locator_value) if action.target else "''"
                lines = ["# [ASSERT]",
                         f"elements = driver.find_elements(By.CSS_SELECTOR, {loc_val})",
                         f"assert len(elements) == {count}"]
            case AssertionType.list_contains:
                lines.append(f"assert {repr(str(val))} in element.text")
            case _:
                raise RuntimeError(f"Unsupported assertion type: {assertion.assert_type}")

        return lines

    def _assert_cypress(self, action: CIRAction) -> List[str]:
        assertion = action.assertion
        if not assertion:
            raise RuntimeError("ASSERT action missing assertion block")

        val = assertion.expected_value
        attr = action.attribute_name or "class"

        if assertion.assert_type == AssertionType.url_contains:
            return [f"cy.url().should('include', {self._js_string(val)});"]

        if assertion.assert_type == AssertionType.title_equals:
            return [f"cy.title().should('eq', {self._js_string(val)});"]

        if assertion.assert_type == AssertionType.title_contains:
            return [f"cy.title().should('include', {self._js_string(val)});"]

        if assertion.assert_type == AssertionType.page_source_contains:
            return [f"cy.get('body').should('contain', {self._js_string(val)});"]

        if not action.target:
            raise RuntimeError("Cypress assertion missing target locator")

        loc = self._locator(action, framework="cypress")

        match assertion.assert_type:
            case AssertionType.text_equals:
                return [f"{loc}.should('have.text', {self._js_string(val)});"]
            case AssertionType.text_contains:
                return [f"{loc}.should('contain', {self._js_string(val)});"]
            case AssertionType.element_is_visible:
                return [f"{loc}.should('be.visible');"]
            case AssertionType.element_enabled:
                return [f"{loc}.should('be.enabled');"]
            case AssertionType.element_disabled:
                return [f"{loc}.should('be.disabled');"]
            case AssertionType.element_checked:
                return [f"{loc}.should('be.checked');"]
            case AssertionType.element_unchecked:
                return [f"{loc}.should('not.be.checked');"]
            case AssertionType.attribute_equals:
                return [f"{loc}.should('have.attr', {self._js_string(attr)}, {self._js_string(val)});"]
            case AssertionType.attribute_contains:
                return [f"{loc}.invoke('attr', {self._js_string(attr)}).should('include', {self._js_string(val)});"]
            case AssertionType.element_value:
                return [f"{loc}.should('have.value', {self._js_string(val)});"]
            case AssertionType.element_count:
                count = action.expected_count or 0
                return [f"{loc}.should('have.length', {count});"]
            case AssertionType.list_contains:
                return [f"{loc}.should('contain', {self._js_string(val)});"]
            case _:
                raise RuntimeError(f"Unsupported assertion type: {assertion.assert_type}")

    # ==================================================
    # LOCATOR RENDERING
    # ==================================================

    def _locator(self, action: CIRAction, *, framework: str) -> str:
        if framework == "playwright":
            return self._locator_playwright(action)
        if framework == "selenium":
            return self._locator_selenium(action)
        if framework == "appium":
            return self._locator_appium(action)
        if framework == "cypress":
            return self._locator_cypress(action)
        raise RuntimeError(f"Unsupported framework: {framework}")

    def _locator_playwright(self, action: CIRAction) -> str:
        loc = action.target
        if not loc:
            raise RuntimeError("Missing locator")

        value = loc.locator_value
        strategy = loc.locator_strategy
        match strategy:
            case LocatorStrategy.css | LocatorStrategy.xpath:
                return f"page.locator({repr(value)})"
            case LocatorStrategy.text:
                return f"page.get_by_text({repr(value)})"
            case LocatorStrategy.role:
                return f"page.get_by_role({value})" if value.startswith(("'", '"')) else f"page.get_by_role({repr(value)})"
            case LocatorStrategy.label:
                return f"page.get_by_label({repr(value)})"
            case LocatorStrategy.placeholder:
                return f"page.get_by_placeholder({repr(value)})"
            case LocatorStrategy.test_id:
                return f"page.get_by_test_id({repr(value)})"
            case LocatorStrategy.name:
                return f"page.locator({repr(f'[name=\"{value}\"]')})"
            case LocatorStrategy.id:
                return f"page.locator({repr('#' + value)})"
            case LocatorStrategy.class_name:
                return f"page.locator({repr('.' + value)})"
            case LocatorStrategy.tag:
                return f"page.locator({repr(value)})"
            case LocatorStrategy.ios_class_chain | LocatorStrategy.ios_predicate_string | LocatorStrategy.android_data_matcher | LocatorStrategy.uiautomator:
                return f"page.locator({repr(value)})"

        raise RuntimeError(f"Unsupported locator strategy: {strategy}")

    def _locator_selenium(self, action: CIRAction) -> str:
        loc = action.target
        if not loc:
            raise RuntimeError("Missing locator")

        value = loc.locator_value
        strategy = loc.locator_strategy
        match strategy:
            case LocatorStrategy.id:
                return f"driver.find_element(By.ID, {repr(value)})"
            case LocatorStrategy.name:
                return f"driver.find_element(By.NAME, {repr(value)})"
            case LocatorStrategy.css:
                return f"driver.find_element(By.CSS_SELECTOR, {repr(value)})"
            case LocatorStrategy.xpath:
                return f"driver.find_element(By.XPATH, {repr(value)})"
            case LocatorStrategy.class_name:
                return f"driver.find_element(By.CLASS_NAME, {repr(value)})"
            case LocatorStrategy.tag:
                return f"driver.find_element(By.TAG_NAME, {repr(value)})"
            case LocatorStrategy.test_id:
                return f"driver.find_element(By.CSS_SELECTOR, {repr(f'[data-testid=\"{value}\"]')})"
            case LocatorStrategy.placeholder:
                return f"driver.find_element(By.CSS_SELECTOR, {repr(f'[placeholder=\"{value}\"]')})"
            case LocatorStrategy.text | LocatorStrategy.label | LocatorStrategy.role:
                text = self._semantic_locator_text(value)
                literal = self._xpath_literal(text)
                xpath = f"//*[normalize-space()={literal} or contains(normalize-space(), {literal})]"
                return f"driver.find_element(By.XPATH, {repr(xpath)})"
            case LocatorStrategy.ios_class_chain | LocatorStrategy.ios_predicate_string | LocatorStrategy.android_data_matcher | LocatorStrategy.uiautomator:
                literal = self._xpath_literal(value)
                return f"driver.find_element(By.XPATH, {repr(f'//*[contains(@class, {literal})]')})"

        raise RuntimeError(f"Unsupported Selenium locator strategy: {strategy}")

    def _locator_appium(self, action: CIRAction) -> str:
        loc = action.target
        if not loc:
            raise RuntimeError("Missing locator")

        value = loc.locator_value
        strategy = loc.locator_strategy
        match strategy:
            case LocatorStrategy.id:
                return f"driver.find_element(AppiumBy.ID, {repr(value)})"
            case LocatorStrategy.xpath:
                return f"driver.find_element(AppiumBy.XPATH, {repr(value)})"
            case LocatorStrategy.class_name:
                return f"driver.find_element(AppiumBy.CLASS_NAME, {repr(value)})"
            case LocatorStrategy.uiautomator:
                return f"driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, {repr(value)})"
            case LocatorStrategy.test_id:
                return f"driver.find_element(AppiumBy.ACCESSIBILITY_ID, {repr(value)})"
            case LocatorStrategy.name:
                return f"driver.find_element(AppiumBy.ACCESSIBILITY_ID, {repr(value)})"
            case LocatorStrategy.ios_class_chain:
                return f"driver.find_element(AppiumBy.IOS_CLASS_CHAIN, {repr(value)})"
            case LocatorStrategy.ios_predicate_string:
                return f"driver.find_element(AppiumBy.IOS_PREDICATE_STRING, {repr(value)})"
            case LocatorStrategy.android_data_matcher:
                return f"driver.find_element(AppiumBy.ANDROID_DATA_MATCHER, {repr(value)})"
            case LocatorStrategy.text | LocatorStrategy.label | LocatorStrategy.placeholder | LocatorStrategy.role:
                text = self._semantic_locator_text(value)
                literal = self._xpath_literal(text)
                xpath = (
                    f"//*[@text={literal} or @content-desc={literal} "
                    f"or contains(@text, {literal}) or contains(@content-desc, {literal})]"
                )
                return f"driver.find_element(AppiumBy.XPATH, {repr(xpath)})"

        raise RuntimeError(f"Unsupported Appium locator strategy: {strategy}")

    def _locator_cypress(self, action: CIRAction) -> str:
        loc = action.target
        if not loc:
            raise RuntimeError("Missing locator")

        value = loc.locator_value
        strategy = loc.locator_strategy
        match strategy:
            case LocatorStrategy.test_id:
                return f"cy.get({self._js_string(f'[data-testid={self._css_attr_value(value)}]')})"
            case LocatorStrategy.id:
                return f"cy.get({self._js_string(f'#{value}')})"
            case LocatorStrategy.css:
                return f"cy.get({self._js_string(value)})"
            case LocatorStrategy.xpath:
                return f"cy.xpath({self._js_string(value)})"
            case LocatorStrategy.name:
                return f"cy.get({self._js_string(f'[name={self._css_attr_value(value)}]')})"
            case LocatorStrategy.class_name:
                return f"cy.get({self._js_string('.' + value)})"
            case LocatorStrategy.tag:
                return f"cy.get({self._js_string(value)})"
            case LocatorStrategy.text | LocatorStrategy.label | LocatorStrategy.placeholder | LocatorStrategy.role:
                return f"cy.contains({self._js_string(self._semantic_locator_text(value))})"
            case LocatorStrategy.ios_class_chain | LocatorStrategy.ios_predicate_string | LocatorStrategy.android_data_matcher | LocatorStrategy.uiautomator:
                return f"cy.get({self._js_string(value)})"

        raise RuntimeError(f"Unsupported Cypress locator strategy: {strategy}")

    # ==================================================
    # INTERNAL HELPERS
    # ==================================================

    def _require_target(self, action: CIRAction, name: str) -> None:
        if not action.target:
            raise RuntimeError(f"{name} action missing target locator")

    def _semantic_locator_text(self, value: str) -> str:
        role_name = re.search(r"name\s*=\s*['\"]([^'\"]+)['\"]", value or "")
        if role_name:
            return role_name.group(1)
        if "," in (value or "") and "name" in value.lower():
            return value.split(",", 1)[-1].split("=", 1)[-1].strip().strip("'\"")
        return str(value)

    @staticmethod
    def _xpath_literal(value: str) -> str:
        if "'" not in value:
            return f"'{value}'"
        if '"' not in value:
            return f'"{value}"'
        parts = value.split("'")
        return "concat(" + ', "\'", '.join(f"'{part}'" for part in parts) + ")"

    @staticmethod
    def _js_string(value) -> str:
        return json.dumps("" if value is None else str(value))

    @staticmethod
    def _css_attr_value(value) -> str:
        escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    def _appium_targetless_type(self, value: str) -> List[str]:
        if value in {"\n", "\r", ""}:
            return [
                "try:",
                "    driver.press_keycode(66)",
                "except Exception:",
                "    driver.switch_to.active_element.send_keys('\\n')",
            ]
        return [f"driver.switch_to.active_element.send_keys({repr(value)})"]
