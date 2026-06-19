from typing import List, Optional, Dict
import json
import hashlib
from datetime import datetime, timezone
import asyncio

from app.models.cir import CIRTestCase, CIRBlock, ActionType, NavigateType, AssertionType, LocatorStrategy, CIRAction
from app.models.context import CIRBlockContext
from app.services.generators.base_generator import BaseGenerator
from app.services.framework_helpers.step_verifier import StepVerifier
from app.services.framework_helpers.step_modifier import StepModifier
from app.core.llm_executor import get_llm_executor
from app.services.validator import CIRValidator
from app.services.framework_helpers.atomic_normalizer import AtomicNormalizer
from app.services.framework_helpers.selenium_templates import (
    generate_selenium_imports,
    generate_selenium_guard,
    generate_selenium_test_wrapper,
    generate_selenium_runner,
)

class SeleniumGenerator(BaseGenerator):
    """
    SELENIUM PYTHON CODE GENERATOR
    """

    def __init__(self):
        llm = get_llm_executor()
        super().__init__(StepVerifier(llm), StepModifier(llm))
        self.validator = CIRValidator()
        self._step_registry: Dict[str, str] = {}
        self._step_defs: Dict[str, List[str]] = {}

    def _fallback_render_action(self, action: CIRAction) -> List[str]:
        lines = []
        
        # 1. Target finding
        find_method = ""
        if action.target:
            strat = action.target.locator_strategy
            val = action.target.locator_value
            
            if strat == LocatorStrategy.id:
                find_method = f"driver.find_element(By.ID, {repr(val)})"
            elif strat == LocatorStrategy.name:
                find_method = f"driver.find_element(By.NAME, {repr(val)})"
            elif strat == LocatorStrategy.css:
                find_method = f"driver.find_element(By.CSS_SELECTOR, {repr(val)})"
            elif strat == LocatorStrategy.xpath:
                find_method = f"driver.find_element(By.XPATH, {repr(val)})"
            elif strat == LocatorStrategy.class_name:
                find_method = f"driver.find_element(By.CLASS_NAME, {repr(val)})"
            elif strat == LocatorStrategy.tag:
                find_method = f"driver.find_element(By.TAG_NAME, {repr(val)})"
            elif strat == LocatorStrategy.test_id:
                find_method = f"driver.find_element(By.CSS_SELECTOR, {repr(f'[data-testid=\"{val}\"]')})"
            else:
                find_method = f"driver.find_element(By.CSS_SELECTOR, {repr(val)})"

        # 2. Emitting Action
        if action.action_type == ActionType.navigate:
            if action.navigate_type == NavigateType.url:
                lines.append(f"    driver.get({repr(action.value)})")
            elif action.navigate_type == NavigateType.back:
                lines.append("    driver.back()")
            elif action.navigate_type == NavigateType.forward:
                lines.append("    driver.forward()")
            elif action.navigate_type == NavigateType.refresh:
                lines.append("    driver.refresh()")

        elif action.action_type == ActionType.click:
            lines.extend([
                f"    element = {find_method}",
                "    element.click()",
            ])

        elif action.action_type == ActionType.type:
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
            lines.extend([
                f"    select = Select({find_method})",
            ])
            mode = action.value_mode or "value"
            if mode == "index":
                lines.append(f"    select.select_by_index({int(action.value)})")
            elif mode == "label":
                lines.append(f"    select.select_by_visible_text({repr(action.value)})")
            else:
                lines.append(f"    select.select_by_value({repr(action.value)})")

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

    def _generate_wait(self, action: CIRAction) -> List[str]:
        # Selenium wait logic fallback if needed
        return []

    def _is_noop_action(self, action: CIRAction) -> bool:
        return (
            action.action_type == ActionType.navigate
            and action.navigate_type == NavigateType.refresh
            and not action.value
        )

    def _is_noop_setup(self, block: CIRBlock) -> bool:
        return len(block.actions) == 1 and self._is_noop_action(block.actions[0])

    def _register_shared_step(self, body: List[str]) -> str:
        normalized = "\n".join(body).strip()
        step_hash = hashlib.sha256(normalized.encode()).hexdigest()[:12]

        if step_hash in self._step_registry:
            return self._step_registry[step_hash]

        fn_name = f"_step_{len(self._step_registry)}_{step_hash}"
        self._step_registry[step_hash] = fn_name
        self._step_defs[fn_name] = body
        return fn_name

    async def generate(
        self,
        cir_test_case: CIRTestCase,
        context_map: dict[str, CIRBlockContext],
    ) -> str:
        normalizer = AtomicNormalizer()
        normalized_steps: List[CIRBlock] = []

        for block in cir_test_case.steps:
            normalized = normalizer.normalize_block(block)
            normalized_steps.append(normalized)

        cir_test_case = CIRTestCase(
            test_case_id=cir_test_case.test_case_id,
            description=cir_test_case.description,
            setup=cir_test_case.setup,
            steps=normalized_steps,
            teardown=cir_test_case.teardown,
        )

        self.validator.validate_blocks(cir_test_case.setup)
        self.validator.validate_blocks(cir_test_case.steps)

        test_id = cir_test_case.test_case_id
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        lines: List[str] = []
        step_calls: List[str] = []

        lines.extend(generate_selenium_imports())
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

            fn = self._register_shared_step(body)
            step_name = f"{step_index}_{fn}"

            step_code_literal = json.dumps("\n".join(body))
            intent_literal = json.dumps(intent)

            step_calls.append(
                f"_guarded_step("
                f"driver, {fn}, '{step_name}', {step_index}, "
                f"{step_code_literal}, {intent_literal}, "
                f"{max_retries}, artifacts_dir, success_dir, step_metrics, running_summary_path)"
            )

        lines.extend(generate_selenium_guard())
        lines.append("")

        for fn, body in self._step_defs.items():
            lines.append(f"def {fn}(driver):")
            for line in body:
                if not line.startswith("    "):
                    lines.append(f"    {line}")
                else:
                    lines.append(line)
            lines.append("")

        lines.extend(generate_selenium_test_wrapper(step_calls, test_id, run_id))
        lines.extend(generate_selenium_runner())

        return "\n".join(lines)
