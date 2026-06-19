from abc import ABC, abstractmethod
from typing import List, Optional, Dict
import logging
import asyncio

from app.models.cir import CIRTestCase, CIRBlock, CIRAction
from app.models.context import CIRBlockContext
from app.services.framework_helpers.step_verifier import StepVerifier
from app.services.framework_helpers.step_modifier import StepModifier
from app.core.config import get_settings

logger = logging.getLogger("base_generator")
settings = get_settings()
DEFAULT_STEP_RETRIES = settings.DEFAULT_STEP_RETRIES
MAX_VERIFIER_REPAIR_ATTEMPTS = settings.MAX_VERIFIER_REPAIR_ATTEMPTS


class BaseGenerator(ABC):
    """
    Abstract Base class for all test code generation engines.
    """

    def __init__(self, verifier: StepVerifier, modifier: StepModifier):
        self.verifier = verifier
        self.modifier = modifier

    @abstractmethod
    async def generate(
        self,
        cir_test_case: CIRTestCase,
        context_map: dict[str, CIRBlockContext],
    ) -> str:
        """
        Generates the target framework script as a string.
        """
        pass

    @abstractmethod
    def _fallback_render_action(self, action: CIRAction) -> List[str]:
        """
        Hardcoded manual string-concatenation fallback if LLM generation fails or for deterministic rendering.
        """
        pass

    @abstractmethod
    def _generate_wait(self, action: CIRAction) -> List[str]:
        """
        Hardcoded manual wait string-concatenation fallback.
        """
        pass

    def get_file_extension(self) -> str:
        return ".py"

    async def _process_single_step(
        self,
        step_index: int,
        block: CIRBlock,
        ctx: Optional[CIRBlockContext],
    ) -> dict:
        body, max_retries = await self._build_step_body(block, ctx)

        if not body:
            raise RuntimeError(
                f"Empty step body after verification | block_id={block.block_id}"
            )

        return {
            "index": step_index,
            "body": body,
            "max_retries": max_retries,
            "intent": block.intent,
        }

    async def _build_step_body(
        self,
        block: CIRBlock,
        block_context: Optional[CIRBlockContext],
    ) -> tuple[List[str], int]:
        matched_script = block_context.matched_script if block_context else None
        matched_script_reference = (
            matched_script.strip() if matched_script and matched_script.strip() else None
        )
        max_retries = DEFAULT_STEP_RETRIES

        def render_from_cir() -> str:
            body: List[str] = []
            for action in block.actions:
                raw_lines = []
                raw_lines.extend(self._generate_wait(action))
                raw_lines.extend(self._fallback_render_action(action))
                body.extend(raw_lines)

            if not body:
                return ""

            code = "\n".join(body)
            # basic cleanup
            return code.strip()

        candidate_code = render_from_cir()
        if not candidate_code:
            return [], max_retries

        # When a matched-script reference is present, keep the deterministic CIR render
        # and skip verifier repair because the step shape is already reference-backed.
        if matched_script_reference:
            logger.info(
                "Matched-script reference present. Using reference-backed deterministic CIR render and bypassing LLM verifier loop."
            )
            return candidate_code.splitlines(), max_retries

        # Self-repair verifier loop
        last_reason = ""
        regeneration_used = False

        matched_script_str = matched_script_reference

        for attempt in range(MAX_VERIFIER_REPAIR_ATTEMPTS):
            res = await self.verifier.verify(
                intent=block.intent,
                generated_code=candidate_code,
                matched_script=matched_script_str,
            )
            verified = res.get("verdict") == "correct"
            reason = res.get("reason", "")

            if verified:
                return candidate_code.splitlines(), max_retries

            last_reason = reason or "Verification failed"

            verification_mode = "INTENT_ONLY" if not matched_script_str else "INTENT_PLUS_REFERENCE"
            modified = await self.modifier.modify(
                intent=block.intent,
                generated_code=candidate_code,
                matched_script=matched_script_str,
                reason=last_reason,
                verification_mode=verification_mode,
            )

            if modified:
                if modified == candidate_code:
                    break  # Early break on unmodified retry loop
                try:
                    candidate_code = modified
                    continue
                except Exception:
                    pass

            if not regeneration_used:
                regeneration_used = True
                candidate_code = render_from_cir()
                continue

        raise RuntimeError(
            f"Failed to satisfy intent after {MAX_VERIFIER_REPAIR_ATTEMPTS} attempts | "
            f"intent={block.intent} | last_reason={last_reason}"
        )
