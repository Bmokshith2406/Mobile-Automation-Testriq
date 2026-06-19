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
from app.services.framework_helpers.cypress_templates import (
    generate_cypress_imports,
    generate_cypress_test_wrapper,
)

class CypressGenerator(BaseGenerator):
    """
    CYPRESS JS CODE GENERATOR
    """

    def __init__(self):
        llm = get_llm_executor()
        super().__init__(StepVerifier(llm), StepModifier(llm))
        self.validator = CIRValidator()
        self._step_registry: Dict[str, str] = {}
        self._step_defs: Dict[str, List[str]] = {}

    def get_file_extension(self) -> str:
        return ".js"

    def _fallback_render_action(self, action: CIRAction) -> List[str]:
        lines = []
        
        # 1. Target finding
        find_method = ""
        if action.target:
            strat = action.target.locator_strategy
            val = action.target.locator_value
            
            if strat == LocatorStrategy.test_id:
                find_method = f"cy.get({self._js_string(f'[data-testid={self._css_attr_value(val)}]')})"
            elif strat == LocatorStrategy.id:
                find_method = f"cy.get({self._js_string(f'#{val}')})"
            elif strat == LocatorStrategy.css:
                find_method = f"cy.get({self._js_string(val)})"
            elif strat == LocatorStrategy.xpath:
                find_method = f"cy.xpath({self._js_string(val)})"
            elif strat == LocatorStrategy.name:
                find_method = f"cy.get({self._js_string(f'[name={self._css_attr_value(val)}]')})"
            else:
                find_method = f"cy.get({self._js_string(val)})"

        # 2. Emitting action
        if action.action_type == ActionType.navigate:
            if action.navigate_type == NavigateType.url:
                lines.append(f"cy.visit({self._js_string(action.value)});")
            elif action.navigate_type == NavigateType.back:
                lines.append("cy.go('back');")
            elif action.navigate_type == NavigateType.forward:
                lines.append("cy.go('forward');")
            elif action.navigate_type == NavigateType.refresh:
                lines.append("cy.reload();")

        elif action.action_type == ActionType.click:
            lines.append(f"{find_method}.should('be.visible').click();")

        elif action.action_type == ActionType.type:
            lines.append(f"{find_method}.should('be.visible').type({self._js_string(action.value)});")

        elif action.action_type == ActionType.clear:
            lines.append(f"{find_method}.should('be.visible').clear();")

        elif action.action_type == ActionType.select:
            lines.append(f"{find_method}.should('be.visible').select({self._js_string(action.value)});")

        elif action.action_type == ActionType.assert_action:
            assertion = action.assertion
            if assertion.assert_type == AssertionType.element_is_visible:
                lines.append(f"{find_method}.should('be.visible');")
            elif assertion.assert_type == AssertionType.text_equals:
                lines.append(f"{find_method}.should('have.text', {self._js_string(assertion.expected_value)});")
            elif assertion.assert_type == AssertionType.text_contains:
                lines.append(f"{find_method}.should('contain', {self._js_string(assertion.expected_value)});")
            elif assertion.assert_type == AssertionType.url_contains:
                lines.append(f"cy.url().should('include', {self._js_string(assertion.expected_value)});")
            elif assertion.assert_type == AssertionType.title_contains:
                lines.append(f"cy.title().should('include', {self._js_string(assertion.expected_value)});")
            elif assertion.assert_type == AssertionType.title_equals:
                lines.append(f"cy.title().should('eq', {self._js_string(assertion.expected_value)});")

        return lines

    def _generate_wait(self, action: CIRAction) -> List[str]:
        # Cypress wait logic fallback
        return []

    def _is_noop_action(self, action: CIRAction) -> bool:
        return (
            action.action_type == ActionType.navigate
            and action.navigate_type == NavigateType.refresh
            and not action.value
        )

    def _is_noop_setup(self, block: CIRBlock) -> bool:
        return len(block.actions) == 1 and self._is_noop_action(block.actions[0])

    @staticmethod
    def _js_string(value) -> str:
        import json
        return json.dumps("" if value is None else str(value))

    @staticmethod
    def _css_attr_value(value) -> str:
        escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

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

        lines.extend(generate_cypress_imports())
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

            step_name = f"step_{step_index}"
            step_lines = [f"  it('{step_name}', () => {{"]
            for line in body:
                step_lines.append(f"    {line}")
            step_lines.append("  });")
            step_lines.append("")
            
            step_calls.extend(step_lines)

        lines.extend(generate_cypress_test_wrapper(step_calls, test_id, run_id))

        return "\n".join(lines)
