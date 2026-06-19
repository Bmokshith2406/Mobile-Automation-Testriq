from typing import List, Optional, Dict
import json
import hashlib
import ast
from datetime import datetime, timezone
import asyncio

from app.models.cir import CIRTestCase, CIRBlock, ActionType, NavigateType, AssertionType, LocatorStrategy, CIRAction
from app.models.appium import AppiumConfig
from app.models.context import CIRBlockContext
from app.services.generators.base_generator import BaseGenerator
from app.services.framework_helpers.step_verifier import StepVerifier
from app.services.framework_helpers.step_modifier import StepModifier
from app.core.llm_executor import get_llm_executor
from app.services.validator import CIRValidator
from app.services.framework_helpers.atomic_normalizer import AtomicNormalizer
from app.services.framework_helpers.appium_templates import (
    generate_appium_imports,
    generate_appium_guard,
    generate_appium_test_wrapper,
    generate_appium_runner,
)

class AppiumGenerator(BaseGenerator):
    """
    APPIUM PYTHON CODE GENERATOR
    """

    def __init__(self):
        llm = get_llm_executor()
        super().__init__(StepVerifier(llm), StepModifier(llm))
        self.validator = CIRValidator()
        self._step_registry: Dict[str, str] = {}
        self._step_defs: Dict[str, List[str]] = {}

    def _fallback_render_action(self, action: CIRAction) -> List[str]:
        lines = []
        
        find_method = ""
        if action.target:
            strat = action.target.locator_strategy
            val = action.target.locator_value
            
            if strat == LocatorStrategy.test_id:
                # Appium maps test_id to Accessibility ID
                find_method = f"driver.find_element(AppiumBy.ACCESSIBILITY_ID, {repr(val)})"
            elif strat == LocatorStrategy.id:
                find_method = f"driver.find_element(AppiumBy.ID, {repr(val)})"
            elif strat == LocatorStrategy.xpath:
                find_method = f"driver.find_element(AppiumBy.XPATH, {repr(val)})"
            elif strat == LocatorStrategy.class_name:
                find_method = f"driver.find_element(AppiumBy.CLASS_NAME, {repr(val)})"
            elif strat == LocatorStrategy.uiautomator:
                find_method = f"driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, {repr(val)})"
            elif strat == LocatorStrategy.text:
                xpath = f"//*[@text={repr(val)} or @content-desc={repr(val)} or contains(@text, {repr(val)}) or contains(@content-desc, {repr(val)})]"
                find_method = f"driver.find_element(AppiumBy.XPATH, {repr(xpath)})"
            else:
                find_method = f"driver.find_element(AppiumBy.ACCESSIBILITY_ID, {repr(val)})"

        # Emitting actions
        if action.action_type == ActionType.navigate:
            if action.navigate_type == NavigateType.back:
                lines.append("    driver.back()")
            elif action.navigate_type == NavigateType.forward:
                lines.append("    driver.forward()")
            elif action.navigate_type == NavigateType.refresh:
                lines.append("    driver.refresh()")
            elif action.navigate_type == NavigateType.url:
                lines.append(f"    driver.get({repr(action.value)})")

        elif action.action_type == ActionType.click:
            lines.extend([
                f"    element = {find_method}",
                "    element.click()",
            ])

        elif action.action_type == ActionType.type:
            if not action.target:
                lines.extend(self._render_targetless_type(action.value))
            else:
                lines.extend([
                    f"    element = {find_method}",
                    f"    element.send_keys({repr(action.value)})",
                ])

        elif action.action_type == ActionType.clear:
            lines.extend([
                f"    element = {find_method}",
                "    element.clear()",
            ])

        elif action.action_type == ActionType.select:
            option_xpath = f"//*[@text='{action.value}' or @content-desc='{action.value}']"
            lines.extend([
                f"    element = {find_method}",
                "    element.click()",
                f"    option = driver.find_element(AppiumBy.XPATH, {repr(option_xpath)})",
                "    option.click()",
            ])

        elif action.action_type == ActionType.assert_action:
            assertion = action.assertion
            lines.append("    # [ASSERT]")
            if assertion.assert_type == AssertionType.element_is_visible:
                lines.extend([
                    f"    element = {find_method}",
                    "    assert element.is_displayed()",
                ])
            elif assertion.assert_type == AssertionType.text_equals:
                lines.extend([
                    f"    element = {find_method}",
                    f"    assert element.text == {repr(assertion.expected_value)}",
                ])
            elif assertion.assert_type == AssertionType.text_contains:
                lines.extend([
                    f"    element = {find_method}",
                    f"    assert {repr(assertion.expected_value)} in element.text",
                ])
            elif assertion.assert_type == AssertionType.url_contains:
                lines.append(f"    assert {repr(assertion.expected_value)} in driver.current_url")
            elif assertion.assert_type == AssertionType.title_contains:
                lines.append(f"    assert {repr(assertion.expected_value)} in driver.title")
            elif assertion.assert_type == AssertionType.title_equals:
                lines.append(f"    assert driver.title == {repr(assertion.expected_value)}")

        return lines

    def _render_targetless_type(self, value: Optional[str]) -> List[str]:
        if value in {"\n", "\r", "\ue007"}:
            return [
                "    try:",
                "        driver.press_keycode(66)",
                "    except Exception:",
                "        driver.switch_to.active_element.send_keys('\\n')",
            ]

        return [
            f"    driver.switch_to.active_element.send_keys({repr(value or '')})",
        ]

    def _generate_wait(self, action: CIRAction) -> List[str]:
        return []

    def _is_noop_action(self, action: CIRAction) -> bool:
        return (
            action.action_type == ActionType.navigate
            and action.navigate_type == NavigateType.refresh
            and not action.value
        )

    def _is_noop_setup(self, block: CIRBlock) -> bool:
        return len(block.actions) == 1 and self._is_noop_action(block.actions[0])

    async def generate(
        self,
        cir_test_case: CIRTestCase,
        context_map: dict[str, CIRBlockContext],
    ) -> str:
        self._step_registry = {}
        self._step_defs = {}

        normalizer = AtomicNormalizer()
        normalized_steps: List[CIRBlock] = []

        for block in cir_test_case.steps:
            normalized = normalizer.normalize_block(block)
            normalized_steps.append(normalized)

        cir_test_case = CIRTestCase(
            test_case_id=cir_test_case.test_case_id,
            description=cir_test_case.description,
            appium_config=cir_test_case.appium_config,
            setup=cir_test_case.setup,
            steps=normalized_steps,
            teardown=cir_test_case.teardown,
        )

        appium_config = cir_test_case.appium_config or AppiumConfig()

        self.validator.validate_blocks(cir_test_case.setup)
        self.validator.validate_blocks(cir_test_case.steps)

        test_id = cir_test_case.test_case_id
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        lines: List[str] = []
        step_calls: List[str] = []

        lines.extend(generate_appium_imports())
        lines.append("")

        executable_blocks = [
            block
            for block in (cir_test_case.setup + cir_test_case.steps)
            if block.actions and not self._is_noop_setup(block)
        ]

        tasks = []
        for idx, block in enumerate(executable_blocks):
            ctx = context_map.get(block.block_id)
            tasks.append(
                self._process_single_step(idx, block, ctx)
            )

        results = await asyncio.gather(*tasks)
        results.sort(key=lambda r: r["index"])

        for result in results:
            step_index = result["index"]
            body = result["body"]
            max_retries = result["max_retries"]
            intent = result["intent"]

            step_code = "\n".join(body)
            step_code_literal = json.dumps(step_code)
            intent_literal = json.dumps(intent)

            step_hash = hashlib.sha256(step_code.strip().encode()).hexdigest()[:12]
            fn = f"_step_{step_index}_{step_hash}"
            if fn in self._step_defs:
                raise RuntimeError(f"Duplicate Appium step function generated: {fn}")
            self._step_defs[fn] = body
            step_name = f"{step_index}_{fn}"

            step_calls.append(
                f"_guarded_step("
                f"driver, {fn}, '{step_name}', {step_index}, "
                f"{step_code_literal}, {intent_literal}, "
                f"{max_retries}, artifacts_dir, success_dir, step_metrics, "
                f"running_summary_path, device_context)"
            )

        lines.extend(generate_appium_guard())
        lines.append("")

        for fn, body in self._step_defs.items():
            lines.append(f"def {fn}(driver):")
            for line in body:
                if not line.startswith("    "):
                    lines.append(f"    {line}")
                else:
                    lines.append(line)
            lines.append("")

        lines.extend(
            generate_appium_test_wrapper(
                step_calls,
                test_id,
                run_id,
                appium_config,
            )
        )
        lines.extend(generate_appium_runner())

        rendered = "\n".join(lines)
        self._validate_generated_integrity(rendered)
        return rendered

    def _validate_generated_integrity(self, source: str) -> None:
        tree = ast.parse(source)
        lines = source.splitlines(keepends=True)
        functions = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        step_function_names = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("_step_")
        ]
        if len(step_function_names) != len(set(step_function_names)):
            raise RuntimeError("Duplicate Appium step function names generated")

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "_guarded_step":
                continue
            step_fn_node = node.args[1] if len(node.args) > 1 else None
            step_code_node = node.args[4] if len(node.args) > 4 else None
            if not isinstance(step_fn_node, ast.Name):
                continue
            if not isinstance(step_code_node, ast.Constant) or not isinstance(step_code_node.value, str):
                continue
            fn_node = functions.get(step_fn_node.id)
            if not fn_node or not fn_node.body:
                raise RuntimeError(f"Guarded Appium step references missing function: {step_fn_node.id}")
            body_text = self._function_body_source(lines, fn_node)
            if self._normalize_step_source(body_text) != self._normalize_step_source(step_code_node.value):
                raise RuntimeError(
                    f"Guarded Appium source mismatch for {step_fn_node.id}"
                )

    @staticmethod
    def _function_body_source(lines: List[str], node: ast.AST) -> str:
        body = getattr(node, "body", None) or []
        start = body[0].lineno - 1
        end = getattr(body[-1], "end_lineno", body[-1].lineno)
        return "".join(lines[start:end])

    @staticmethod
    def _normalize_step_source(value: str) -> str:
        return "\n".join(
            line.strip()
            for line in (value or "").splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
