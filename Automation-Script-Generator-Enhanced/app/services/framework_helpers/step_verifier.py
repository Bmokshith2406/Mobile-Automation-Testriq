from typing import Optional
import logging

from app.core.llm_executor import get_llm_executor, LLMExecutor
from app.core.llm_json import generate_json
from app.core.json_schemas import STEP_VERIFICATION_SCHEMA
from app.prompts.template_engine import get_template_engine

logger = logging.getLogger("step_verifier")

class StepVerificationError(Exception):
    pass

class StepVerifier:
    """
    SEMANTIC INTENT-FIRST STEP VERIFIER (FRAMEWORK AGNOSTIC)

    Properties:
    - CIR is the source of truth
    - Verifier checks semantic consistency & safety
    - Verifier MUST NOT reinterpret semantics
    - Enforces HARD semantic constraints via prompt
    - No focus inference
    - No keyboard typing
    - No implicit targeting
    - Explicit locator required for TYPE & CLEAR
    """

    VERIFIER_VERSION = "CIR_LOCKED_2.0"

    def __init__(self, llm: Optional[LLMExecutor] = None):
        self.llm = llm or get_llm_executor()
        self.template_engine = get_template_engine()
        logger.info("StepVerifier initialized | mode=LLM_STRICT")

    # ==================================================
    # PUBLIC ENTRY
    # ==================================================

    async def verify(
        self,
        *,
        intent: str,
        generated_code: str,
        matched_script: Optional[str],
    ) -> dict:

        if not intent or not generated_code:
            return {
                "verdict": "incorrect",
                "reason": "missing intent or generated code",
                "verifier_version": self.VERIFIER_VERSION,
            }

        verification_mode = (
            "INTENT_ONLY"
            if not matched_script or not matched_script.strip()
            else "INTENT_PLUS_REFERENCE"
        )

        logger.info("STEP VERIFIER MODE | %s", verification_mode)

        prompt = self.template_engine.render(
            "step_verification",
            intent=intent,
            generated_code=generated_code,
            matched_script=matched_script,
        )

        logger.debug(
            "STEP MATCHED SCRIPT BEGIN\n%s\nSTEP MATCHED SCRIPT END",
            matched_script,
        )

        logger.debug(
            "STEP GENERATED SCRIPT BEGIN\n%s\nSTEP GENERATED SCRIPT END",
            generated_code,
        )

        try:
            result = await generate_json(
                prompt,
                purpose="step_verification_llm_only",
                schema=STEP_VERIFICATION_SCHEMA,
            )
            logger.debug("STEP VERIFIER RAW LLM RESPONSE | %s", result)
        except Exception:
            logger.exception("LLM verification failed")
            return {
                "verdict": "incorrect",
                "reason": "LLM verification failed",
                "verifier_version": self.VERIFIER_VERSION,
            }

        if not isinstance(result, dict):
            return {
                "verdict": "incorrect",
                "reason": "invalid LLM response format",
                "verifier_version": self.VERIFIER_VERSION,
            }

        verdict = result.get("verdict")
        reason = result.get("reason")

        if verdict not in {"correct", "incorrect"} or not isinstance(reason, str) or not reason.strip():
            return {
                "verdict": "incorrect",
                "reason": "LLM response missing valid verdict or reason",
                "verifier_version": self.VERIFIER_VERSION,
            }

        return {
            "verdict": verdict,
            "reason": reason.strip(),
            "verification_mode": verification_mode,
            "verifier_version": self.VERIFIER_VERSION,
        }

    # ==================================================
    # BACKWARD COMPAT
    # ==================================================

    async def verify_atomic(
        self,
        *,
        intent: str,
        generated_code: str,
        matched_script: Optional[str],
    ) -> dict:
        return await self.verify(
            intent=intent,
            generated_code=generated_code,
            matched_script=matched_script,
        )
