# app/services/cir_builder.py
"""
HYBRID HARDENED CIR Builder (CIR-SAFE + RESILIENT)
"""

from typing import List, Optional, Tuple
import re
import logging
import asyncio
import time

from app.models.test_case import TestCase, Step, Prerequisite
from app.models.cir import (
    CIRTestCase,
    CIRBlock,
    CIRAction,
    ActionType,
    NavigateType,
    CIRBlockType,
)
from app.services.build_helpers.framework_role_upgrader import FrameworkRoleUpgrader
from app.services.build_helpers.intent_corrector import IntentCorrector
from app.services.build_helpers.cir_action_builders import CIRActionBuilder
from app.models.context import CIRBlockContext
from app.models.matched_script import MatchedScript
from app.core.llm_json import generate_json
from app.core.json_schemas import STEP_DECOMPOSITION_SCHEMA
from app.prompts.templates import PromptTemplates
from app.utils.sanitization import sanitize_for_prompt
from app.core.metrics import get_metrics
from app.core.config import get_settings

logger = logging.getLogger("cir.builder")


class CIRBuilder:
    """
    Main builder class to orchestrate the CIR generation pipeline.
    """

    def __init__(self):
        self.role_upgrader = FrameworkRoleUpgrader()
        self.intent_corrector = IntentCorrector()
        self.action_builder = CIRActionBuilder()
        self._metrics = get_metrics()

    # =====================================================
    # PUBLIC ENTRY
    # =====================================================

    async def build(
        self,
        test_case: TestCase,
    ) -> Tuple[CIRTestCase, dict[str, CIRBlockContext]]:
        start_time = time.perf_counter()
        context_map: dict[str, CIRBlockContext] = {}

        self._metrics.cir_builds_total.increment()

        try:
            setup_task = self._build_prerequisites(test_case.prerequisites, context_map)
            steps_task = self._build_steps(test_case.steps, context_map)
            teardown_task = self._build_teardown(test_case.teardown_steps, context_map)

            setup_blocks, step_blocks, teardown_blocks = await asyncio.gather(setup_task, steps_task, teardown_task)

            if not step_blocks:
                raise RuntimeError(f"No CIR steps generated for test_case_id={test_case.test_case_id}")

            duration_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.cir_builds_success.increment()
            self._metrics.cir_build_duration_ms.observe(duration_ms)

            return (
                CIRTestCase(
                    test_case_id=test_case.test_case_id,
                    description=test_case.description,
                    appium_config=test_case.appium_config,
                    setup=setup_blocks,
                    steps=step_blocks,
                    teardown=teardown_blocks,
                ),
                context_map,
            )

        except Exception as e:
            self._metrics.cir_builds_failed.increment()
            self._metrics.record_error(f"cir_build_{type(e).__name__}")
            raise

    # =====================================================
    # PREREQUISITES (SAFE + LENIENT FALLBACK)
    # =====================================================

    async def _build_single_prerequisite(
        self,
        idx: int,
        prereq: Prerequisite,
        context_map: dict[str, CIRBlockContext],
    ) -> List[CIRBlock]:
        """Build a single prerequisite block (used for parallel execution)."""
        block_id = f"SETUP_{idx:02d}"
        raw_script = prereq.matched_script.raw_code if prereq.matched_script else None
        context_map[block_id] = CIRBlockContext(matched_script=raw_script)

        # Fast path: if only a URL in description, build navigate directly
        url = None
        if raw_script:
            m = re.search(r"https?://[^\s'\"`)]+", raw_script)
            if m:
                url = m.group(0)
        if not url and prereq.description:
            m = re.search(r"https?://[^\s'\"`)]+", prereq.description)
            if m:
                url = m.group(0)

        is_simple_nav = url and len(prereq.description.strip().split()) <= 6

        if is_simple_nav:
            action = CIRAction(
                action_type=ActionType.navigate,
                navigate_type=NavigateType.url,
                value=url,
            )
            return [CIRBlock(
                block_id=block_id,
                intent=prereq.description,
                actions=[action],
                block_type=CIRBlockType.setup,
            )]

        matched = (
            MatchedScript(
                raw_code=raw_script,
                language=prereq.matched_script.language,
                framework=prereq.matched_script.framework,
            )
            if prereq.matched_script and raw_script
            else None
        )
        sub_blocks = await self._build_block(
            block_id=block_id,
            intent=prereq.description,
            expected=None,
            matched_script=matched,
            context_map=context_map,
        )
        return [
            CIRBlock(
                block_id=b.block_id,
                intent=b.intent,
                actions=b.actions,
                block_type=CIRBlockType.setup,
            )
            for b in sub_blocks
        ]

    async def _build_prerequisites(
        self,
        prerequisites: List[Prerequisite],
        context_map: dict[str, CIRBlockContext],
    ) -> List[CIRBlock]:
        if not prerequisites:
            return []

        tasks = [
            asyncio.create_task(
                self._build_single_prerequisite(idx, prereq, context_map)
            )
            for idx, prereq in enumerate(prerequisites, start=1)
        ]
        results: List[List[CIRBlock]] = await asyncio.gather(*tasks)
        return [block for sublist in results for block in sublist]

    async def _build_teardown(
        self,
        teardown_steps: List[Step],
        context_map: dict[str, CIRBlockContext],
    ) -> List[CIRBlock]:
        if not teardown_steps:
            return []
        tasks = []
        for idx, step in enumerate(teardown_steps, start=1):
            matched = (
                MatchedScript(raw_code=step.matched_script.raw_code, language=step.matched_script.language, framework=step.matched_script.framework)
                if step.matched_script and step.matched_script.raw_code
                else None
            )
            task = asyncio.create_task(
                self._build_block(
                    block_id=f"TEARDOWN_{idx:02d}",
                    intent=step.description,
                    expected=step.expected_outcome,
                    matched_script=matched,
                    context_map=context_map,
                )
            )
            tasks.append(task)
        results = await asyncio.gather(*tasks)
        blocks = []
        for sub_blocks in results:
            for b in sub_blocks:
                blocks.append(CIRBlock(
                    block_id=b.block_id,
                    intent=b.intent,
                    actions=b.actions,
                    block_type=CIRBlockType.teardown,
                ))
        return blocks

    # =====================================================
    # STEPS
    # =====================================================

    async def _build_steps(
        self,
        steps: List[Step],
        context_map: dict[str, CIRBlockContext],
    ) -> List[CIRBlock]:
        tasks: List[asyncio.Task] = []

        for idx, step in enumerate(steps, start=1):
            matched_script = (
                MatchedScript(
                    raw_code=step.matched_script.raw_code,
                    language=step.matched_script.language,
                    framework=step.matched_script.framework,
                )
                if step.matched_script and step.matched_script.raw_code
                else None
            )

            task = asyncio.create_task(
                self._build_block(
                    block_id=f"STEP_{idx:02d}",
                    intent=step.description,
                    expected=step.expected_outcome,
                    matched_script=matched_script,
                    context_map=context_map,
                )
            )
            tasks.append(task)

        # Order is preserved by asyncio.gather
        blocks_list: List[List[CIRBlock]] = await asyncio.gather(*tasks)
        
        # Flatten the list of lists
        blocks = [block for sublist in blocks_list for block in sublist]
        return blocks

    # =====================================================
    # BLOCK
    # =====================================================

    async def _build_block(
        self,
        block_id: str,
        intent: str,
        expected: Optional[str],
        matched_script: Optional[MatchedScript],
        context_map: dict[str, CIRBlockContext],
    ) -> List[CIRBlock]:
        # 1️⃣ Sanitize intent & expected
        sanitized_intent = sanitize_for_prompt(intent)
        sanitized_expected = sanitize_for_prompt(expected) if expected else None

        # 2️⃣ Intent-based script correction
        _intent_correction_enabled = get_settings().INTENT_CORRECTION_ENABLED
        if (
            _intent_correction_enabled
            and matched_script
            and matched_script.raw_code
        ):
            corrected_script = await self.intent_corrector.correct(
                intent=sanitized_intent,
                expected=sanitized_expected,
                raw_code=matched_script.raw_code,
            )

            if corrected_script != matched_script.raw_code:
                logger.info(
                    "Intent correction applied | block_id=%s",
                    block_id,
                )
                matched_script = MatchedScript(
                    raw_code=corrected_script,
                    language=matched_script.language,
                    framework=matched_script.framework,
                )

        # 2.5️⃣ SAFE Playwright role upgrade
        if self._should_apply_role_upgrade(matched_script):
            upgraded_script = await self.role_upgrader.upgrade(
                raw_code=matched_script.raw_code,
            )

            if upgraded_script != matched_script.raw_code:
                logger.warning(
                    "SAFE ROLE UPGRADE APPLIED | block_id=%s",
                    block_id,
                )
                matched_script = MatchedScript(
                    raw_code=upgraded_script,
                    language=matched_script.language,
                    framework=matched_script.framework,
                )

        # 3️⃣ Store FINAL script used for this block
        context_map[block_id] = CIRBlockContext(
            matched_script=matched_script.raw_code if matched_script else None
        )

        # 4️⃣ Atomic intent split
        atomic_intents = await self._split_atomic_intents(
            intent=sanitized_intent,
            expected=sanitized_expected,
            matched_script=matched_script.raw_code if matched_script else None,
        )

        blocks: List[CIRBlock] = []

        for idx, atomic_intent in enumerate(atomic_intents, start=1):
            if len(atomic_intents) > 1:
                sub_block_id = f"{block_id}_{idx:02d}"
            else:
                sub_block_id = block_id

            # 5️⃣ Build CIR action (delegated to action builder)
            current_expected = sanitized_expected if idx == len(atomic_intents) else None

            action = await self.action_builder.build_action_safe(
                atomic_intent=atomic_intent,
                expected=current_expected,
                matched_script=matched_script,
            )

            if not isinstance(action, CIRAction):
                raise RuntimeError(
                    f"Atomic intent did not produce CIRAction | block_id={sub_block_id}"
                )

            # Store the sub_block context map mapping
            context_map[sub_block_id] = CIRBlockContext(
                matched_script=matched_script.raw_code if matched_script else None
            )

            blocks.append(
                CIRBlock(
                    block_id=sub_block_id,
                    intent=atomic_intent,
                    actions=[action],
                )
            )

        return blocks

    @staticmethod
    def _should_apply_role_upgrade(matched_script: Optional[MatchedScript]) -> bool:
        return (
            matched_script is not None
            and bool(matched_script.raw_code)
            and matched_script.framework.strip().lower() == "playwright"
        )

    # =====================================================
    # ATOMIC SPLIT (STRICT)
    # =====================================================

    async def _split_atomic_intents(
        self,
        intent: str,
        expected: Optional[str],
        matched_script: Optional[str],
    ) -> List[str]:
        prompt = PromptTemplates.step_decomposition(
            intent=intent,
            expected=expected,
            script=matched_script,
        )

        try:
            data = await generate_json(
                prompt,
                purpose="step_decomposition",
                use_cache=False,
                schema=STEP_DECOMPOSITION_SCHEMA,
            )
        except Exception as e:
            logger.error("Atomic split LLM failure | error=%s", e)
            return [intent]

        steps = data.get("atomic_steps") if isinstance(data, dict) else None

        if not isinstance(steps, list):
            return [intent]

        cleaned = [s.strip() for s in steps if isinstance(s, str) and s.strip()]

        # If LLM just returned the original intent unsplit, try heuristic splitting
        if len(cleaned) == 1 and cleaned[0].strip() == intent.strip():
            heuristic = self._heuristic_split(intent)
            if len(heuristic) > 1:
                return heuristic
        return cleaned or [intent]

    def _heuristic_split(self, intent: str) -> List[str]:
        parts = re.split(
            r'\s+(?:and then|then|after that|,\s*then|;\s*then)\s+',
            intent,
            flags=re.IGNORECASE,
        )
        if len(parts) > 1:
            return [p.strip() for p in parts if p.strip()]
        return [intent]

