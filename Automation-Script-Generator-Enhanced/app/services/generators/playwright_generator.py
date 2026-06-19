from typing import List, Optional, Dict
import re
import logging
import asyncio
import time
import json
import hashlib
from datetime import datetime, timezone

from app.models.cir import (
    CIRTestCase,
    CIRBlock,
    CIRAction,
    ActionType,
    NavigateType,
    AssertionType,
)
from app.models.context import CIRBlockContext
from app.services.generators.base_generator import BaseGenerator
from app.services.framework_helpers.step_verifier import StepVerifier
from app.services.framework_helpers.atomic_normalizer import AtomicNormalizer
from app.services.framework_helpers.step_modifier import StepModifier
from app.core.llm_executor import get_llm_executor
from app.services.validator import CIRValidator
from app.services.framework_helpers.playwright_templates import (
    generate_playwright_imports,
    generate_playwright_guard,
    generate_playwright_test_wrapper,
    generate_playwright_runner,
)
from app.services.framework_helpers.action_renderer import ActionRenderer
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger("playwright_generator")
DEFAULT_STEP_RETRIES = settings.DEFAULT_STEP_RETRIES
MAX_VERIFIER_REPAIR_ATTEMPTS = settings.MAX_VERIFIER_REPAIR_ATTEMPTS


class PlaywrightPythonGenerator(BaseGenerator):
    """
    MODULAR PLAYWRIGHT GENERATOR
    """

    def __init__(self):
        llm = get_llm_executor()
        super().__init__(StepVerifier(llm), StepModifier(llm))
        self.validator = CIRValidator()
        self.action_renderer = ActionRenderer()

        self._step_registry: Dict[str, str] = {}
        self._step_defs: Dict[str, List[str]] = {}

    def _fallback_render_action(self, action: CIRAction) -> List[str]:
        return self.action_renderer.render_action(action)

    def _generate_wait(self, action: CIRAction) -> List[str]:
        return self.action_renderer.generate_wait(action)

    async def generate(
        self,
        cir_test_case: CIRTestCase,
        context_map: dict[str, CIRBlockContext],
    ) -> str:
        self._step_registry = {}
        self._step_defs = {}

        # 1. Normalize steps
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

        # 🔒 Hard validation
        self.validator.validate_blocks(cir_test_case.setup)
        self.validator.validate_blocks(cir_test_case.steps)

        test_id = cir_test_case.test_case_id
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        lines: List[str] = []
        step_calls: List[str] = []

        lines.extend(generate_playwright_imports())
        lines.append("")

        # 2. Collect executable blocks
        executable_blocks = [
            block
            for block in (cir_test_case.setup + cir_test_case.steps)
            if block.actions and not self._is_noop_setup(block)
        ]

        # 3. Parallel step building
        tasks = []
        for idx, block in enumerate(executable_blocks):
            ctx = context_map.get(block.block_id)
            tasks.append(
                self._process_single_step(idx, block, ctx)
            )

        results = await asyncio.gather(*tasks)

        # 4. Serial commit
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
                f"await _guarded_step("
                f"page, {fn}, '{step_name}', {step_index}, "
                f"{step_code_literal}, {intent_literal}, "
                f"{max_retries}, artifacts_dir, success_dir, step_metrics, running_summary_path)"
            )

        # 5. Build final script body
        lines.extend(generate_playwright_guard())
        lines.append("")

        for fn, body in self._step_defs.items():
            lines.append(f"async def {fn}(page):")
            for line in body:
                lines.append(f"    {line}")
            lines.append("")

        lines.extend(generate_playwright_test_wrapper(step_calls, test_id, run_id))
        lines.extend(generate_playwright_runner())

        return "\n".join(lines)





    def _register_shared_step(self, body: List[str]) -> str:
        normalized = "\n".join(body).strip()
        step_hash = hashlib.sha256(normalized.encode()).hexdigest()[:12]

        if step_hash in self._step_registry:
            return self._step_registry[step_hash]

        fn_name = f"_step_{len(self._step_registry)}_{step_hash}"
        self._step_registry[step_hash] = fn_name
        self._step_defs[fn_name] = body
        return fn_name

    def _is_noop_action(self, action: CIRAction) -> bool:
        return (
            action.action_type == ActionType.navigate
            and action.navigate_type == NavigateType.refresh
            and not action.value
        )

    def _is_noop_setup(self, block: CIRBlock) -> bool:
        return len(block.actions) == 1 and self._is_noop_action(block.actions[0])


