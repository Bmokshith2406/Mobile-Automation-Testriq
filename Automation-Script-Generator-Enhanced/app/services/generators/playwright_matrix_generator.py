from typing import List, Optional, Dict
import asyncio
import json
from datetime import datetime, timezone

from app.models.cir import CIRTestCase, CIRBlock
from app.models.context import CIRBlockContext
from app.services.generators.base_generator import BaseGenerator
from app.services.generators.playwright_generator import PlaywrightPythonGenerator
from app.services.framework_helpers.playwright_templates import (
    generate_playwright_imports,
    generate_playwright_guard,
    generate_playwright_test_wrapper,
    generate_playwright_runner,
)

TARGET_PROFILES = [
    {"name": "chromium", "engine": "chromium", "device": None},
    {"name": "firefox", "engine": "firefox", "device": None},
    {"name": "webkit", "engine": "webkit", "device": None},
    {"name": "iphone_14_pro", "engine": "webkit", "device": "iPhone 14 Pro"},
    {"name": "pixel_7", "engine": "chromium", "device": "Pixel 7"},
    {"name": "ipad_pro_11", "engine": "webkit", "device": "iPad Pro 11"},
]

class PlaywrightMatrixGenerator(BaseGenerator):
    """
    Generates multiple Playwright test scripts tailored for different browser engines and devices.
    Delegates the heavy lifting of step generation to the core PlaywrightPythonGenerator.
    """

    def __init__(self):
        self._core_generator = PlaywrightPythonGenerator()

    async def generate(
        self,
        cir_test_case: CIRTestCase,
        context_map: dict[str, CIRBlockContext],
    ) -> Dict[str, str]:
        """
        Returns a mapping of script filenames to their generated Python source code.
        """
        # We leverage the core generator to normalize, validate, and build the steps.
        # But we only want to build the step calls once.
        # We'll intercept the generation process to just get the body components.

        # 1. Normalize steps
        from app.services.framework_helpers.atomic_normalizer import AtomicNormalizer
        normalizer = AtomicNormalizer()
        normalized_steps: List[CIRBlock] = []

        for block in cir_test_case.steps:
            normalized = normalizer.normalize_block(block)
            normalized_steps.append(normalized)

        cir_test_case_normalized = CIRTestCase(
            test_case_id=cir_test_case.test_case_id,
            description=cir_test_case.description,
            setup=cir_test_case.setup,
            steps=normalized_steps,
            teardown=cir_test_case.teardown,
        )

        # 2. Hard validation
        self._core_generator.validator.validate_blocks(cir_test_case_normalized.setup)
        self._core_generator.validator.validate_blocks(cir_test_case_normalized.steps)

        test_id = cir_test_case_normalized.test_case_id
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        # 3. Collect executable blocks
        executable_blocks = [
            block
            for block in (cir_test_case_normalized.setup + cir_test_case_normalized.steps)
            if block.actions and not self._core_generator._is_noop_setup(block)
        ]

        # 4. Parallel step building (LLM / verification happens here ONCE)
        tasks = []
        for idx, block in enumerate(executable_blocks):
            ctx = context_map.get(block.block_id)
            tasks.append(
                self._core_generator._process_single_step(idx, block, ctx)
            )

        results = await asyncio.gather(*tasks)

        # 5. Build core definitions and step calls (ONCE)
        results.sort(key=lambda r: r["index"])
        
        step_calls: List[str] = []
        shared_defs: List[str] = []

        for result in results:
            step_index = result["index"]
            body = result["body"]
            max_retries = result["max_retries"]
            intent = result["intent"]

            fn = self._core_generator._register_shared_step(body)
            step_name = f"{step_index}_{fn}"

            step_code_literal = json.dumps("\n".join(body))
            intent_literal = json.dumps(intent)

            step_calls.append(
                f"await _guarded_step("
                f"page, {fn}, '{step_name}', {step_index}, "
                f"{step_code_literal}, {intent_literal}, "
                f"{max_retries}, artifacts_dir, success_dir, step_metrics, running_summary_path)"
            )

        shared_defs.extend(generate_playwright_imports())
        shared_defs.append("")
        shared_defs.extend(generate_playwright_guard())
        shared_defs.append("")

        for fn, body in self._core_generator._step_defs.items():
            shared_defs.append(f"async def {fn}(page):")
            for line in body:
                shared_defs.append(f"    {line}")
            shared_defs.append("")

        shared_prefix_str = "\n".join(shared_defs)

        # 6. Generate individual script for each target
        generated_scripts: Dict[str, str] = {}
        for target in TARGET_PROFILES:
            target_name = target["name"]
            browser_engine = target["engine"]
            device_name = target["device"]

            lines: List[str] = []
            lines.append(shared_prefix_str)
            
            lines.extend(generate_playwright_test_wrapper(
                step_calls, 
                test_id, 
                run_id, 
                target_name=target_name,
                browser_engine=browser_engine,
                device_name=device_name,
            ))
            lines.extend(generate_playwright_runner())

            filename = f"test_{target_name}.py"
            generated_scripts[filename] = "\n".join(lines)

        return generated_scripts
