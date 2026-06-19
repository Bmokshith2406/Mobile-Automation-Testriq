# app/services/step_verifier.py

import logging
from typing import Optional

from app.core.llm_executor import LLMExecutor
from app.core.prompts import build_step_verifier_prompt
from app.models.llm_structured import VerifierResult

logger = logging.getLogger("step_verifier")


class StepVerificationResult(dict):
    """
    Dict subclass that supports both dict-style access and property access for .passed.
    """
    @property
    def passed(self) -> bool:
        return self.get("verdict") == "correct"


class StepVerifier:
    """
    PURE LLM-ONLY STEP VERIFIER

    Uses Gemini structured output (response_mime_type=application/json +
    response_schema=VerifierResult) so the model is constrained to emit
    valid JSON at the API level — no prompt-level JSON instructions, no
    post-hoc regex extraction.

    Properties:
    - ZERO deterministic semantic checks
    - ZERO regex / static guards on meaning
    - LLM is the ONLY decision maker
    - Mandatory explanation for every verdict
    - Structural validation ONLY:
      - Ensures verdict format correctness
      - Ensures explanation presence
    """

    VERIFIER_VERSION = "LLM_STRUCTURED_2.0"

    def __init__(self, llm: Optional[LLMExecutor] = None):
        self.llm = llm or LLMExecutor.get_instance()
        logger.warning("StepVerifier initialized | mode=LLM_STRUCTURED")

    # ==================================================
    # PUBLIC ENTRY
    # ==================================================

    async def verify(
        self,
        generated_code: Optional[str] = None,
        intent: Optional[str] = None,
        matched_script: Optional[str] = None,
        *,
        error_message: Optional[str] = None,
        failure_history: Optional[list[str]] = None,
        **kwargs,
    ) -> StepVerificationResult:

        # Handle kwargs mappings for keyword-only parameters or aliases
        if "generated_code" in kwargs:
            generated_code = kwargs["generated_code"]
        if "intent" in kwargs:
            intent = kwargs["intent"]
        if "matched_script" in kwargs:
            matched_script = kwargs["matched_script"]
        if "error_message" in kwargs:
            error_message = kwargs["error_message"]
        if "failure_history" in kwargs:
            failure_history = kwargs["failure_history"]

        intent = intent or ""
        generated_code = generated_code or ""

        verification_mode = (
            "INTENT_ONLY"
            if not matched_script or not matched_script.strip()
            else "INTENT_PLUS_REFERENCE"
        )

        logger.warning(
            "STEP VERIFIER START | mode=%s | version=%s",
            verification_mode,
            self.VERIFIER_VERSION,
        )

        framework = kwargs.get("framework") or "playwright"
        prompt = build_step_verifier_prompt(
            verification_mode=verification_mode,
            intent=intent,
            matched_script=matched_script,
            generated_code=generated_code,
            error_message=error_message or "N/A",
            failure_history=failure_history,
            framework=framework,
        )

        try:
            raw = await self.llm.run_verifier_structured(prompt, VerifierResult)
            logger.debug("STEP VERIFIER RAW LLM RESPONSE | %r", raw)
        except Exception:
            logger.exception("LLM verification failed")
            return self._failure_response(
                reason="LLM verification failed",
                verification_mode=verification_mode,
            )

        if not raw:
            return self._failure_response(
                reason="LLM returned empty response",
                verification_mode=verification_mode,
            )

        try:
            result = VerifierResult.model_validate_json(raw)
        except Exception:
            logger.warning(
                "STEP VERIFIER STRUCTURED PARSE FAILED | raw=%r",
                raw[:200] if raw else "",
            )
            return self._failure_response(
                reason="Failed to parse structured LLM response",
                verification_mode=verification_mode,
            )

        logger.info(
            "STEP VERIFIER NORMALIZED | verdict=%s | reason_preview=%s",
            result.verdict,
            self._preview_reason(result.reason),
        )

        return StepVerificationResult({
            "verdict": result.verdict,
            "reason": result.reason.strip(),
            "verification_mode": verification_mode,
            "verifier_version": self.VERIFIER_VERSION,
        })

    # ==================================================
    # HELPERS
    # ==================================================

    @staticmethod
    def _preview_reason(reason: Optional[str], limit: int = 180) -> str:
        compact = (reason or "").strip().replace("\r", "\\r").replace("\n", "\\n")
        if len(compact) <= limit:
            return compact
        return compact[:limit] + "...[truncated]"

    # ==================================================
    # FAILURE RESPONSE (CENTRALIZED)
    # ==================================================

    def _failure_response(
        self,
        *,
        reason: str,
        verification_mode: str,
    ) -> StepVerificationResult:
        return StepVerificationResult({
            "verdict": "incorrect",
            "reason": reason,
            "verification_mode": verification_mode,
            "verifier_version": self.VERIFIER_VERSION,
        })

    # ==================================================
    # BACKWARD COMPAT
    # ==================================================

    async def verify_atomic(
        self,
        *,
        intent: str,
        generated_code: str,
        matched_script: Optional[str],
        error_message: Optional[str] = None,
        previous_failed_code: Optional[str] = None,
    ) -> dict:

        history = [previous_failed_code] if previous_failed_code else None

        return await self.verify(
            intent=intent,
            generated_code=generated_code,
            matched_script=matched_script,
            error_message=error_message,
            failure_history=history,
        )
