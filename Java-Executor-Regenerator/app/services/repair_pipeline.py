# Revised pipeline: primary repair for every framework, fallback only after primary cannot fix.
import logging
import re
from typing import Optional, Tuple
from copy import deepcopy

from app.models.step_repair import StepRepairRequest
from app.models.cir import CIRBlockType, ActionType
from app.services.cir_builder import CIRBuilder
from app.services.generator import StepCodeGenerator
from app.services.step_verifier import StepVerifier
from app.services.step_modifier import StepModifier
from app.core.exceptions import StepNotRepairableError
from app.core.metrics import get_metrics

logger = logging.getLogger("pipeline.repair")

_cir_builder: Optional[CIRBuilder] = None
_generator: Optional[StepCodeGenerator] = None
_verifier: Optional[StepVerifier] = None
_modifier: Optional[StepModifier] = None


def _get_cir_builder() -> CIRBuilder:
    global _cir_builder
    if _cir_builder is None:
        _cir_builder = CIRBuilder()
    return _cir_builder


def _get_generator() -> StepCodeGenerator:
    global _generator
    if _generator is None:
        _generator = StepCodeGenerator()
    return _generator


def _get_verifier() -> StepVerifier:
    global _verifier
    if _verifier is None:
        _verifier = StepVerifier()
    return _verifier


def _get_modifier() -> StepModifier:
    global _modifier
    if _modifier is None:
        _modifier = StepModifier()
    return _modifier


def _normalize_code_for_compare(code: Optional[str]) -> str:
    if not code:
        return ""
    lines = [ln.rstrip() for ln in code.replace("\r\n", "\n").split("\n")]
    return "\n".join(lines).strip()


def _extract_string_literals(text: Optional[str]) -> list[str]:
    if not text:
        return []
    literals: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r'(["\'])(.*?)\1', text, flags=re.DOTALL):
        value = match.group(2).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        literals.append(value)
    return literals


def _should_stop_for_appium_state_mismatch(
    *,
    req: StepRepairRequest,
    primary_error: Exception,
) -> Optional[StepNotRepairableError]:
    if (req.framework or "").strip().lower() != "appium":
        return None

    primary_reason = str(primary_error or "").lower()
    if "no locator extracted" not in primary_reason:
        return None

    error_message = (req.error_details.message or "").lower()
    if not any(
        marker in error_message
        for marker in (
            "nosuchelement",
            "no such element",
            "unable to locate element",
        )
    ):
        return None

    dom_snapshot = ((req.artifacts.dom_snapshot if req.artifacts else None) or "").lower()
    if not dom_snapshot:
        return None

    original_targets = [
        value
        for value in _extract_string_literals(req.original_code)
        if value.strip()
    ]
    if not original_targets:
        return None

    if any(target.lower() in dom_snapshot for target in original_targets):
        return None

    return StepNotRepairableError(
        "Appium UI state mismatch prevented same-step repair; the original target is absent from the current screen",
        details={
            "step_id": req.step_id,
            "framework": req.framework,
            "primary_error": str(primary_error),
            "original_targets": original_targets[:5],
        },
    )


async def execute_repair_pipeline(
    *,
    request: StepRepairRequest,
    error_image_bytes: Optional[bytes],
    request_id: str,
) -> Tuple[str, str]:
    req = deepcopy(request)
    framework = (req.framework or "playwright").strip().lower()
    req.framework = framework

    if error_image_bytes:
        if not getattr(req, "artifacts", None):
            raise StepNotRepairableError("Artifacts missing in request")
        req.artifacts.error_image_bytes = error_image_bytes

    try:
        return await _run_primary_repair(req=req, request_id=request_id)
    except StepNotRepairableError as exc:
        logger.info(
            "PIPELINE_PRIMARY_UNABLE | request_id=%s | step_id=%s | framework=%s | reason=%s",
            request_id,
            req.step_id,
            framework,
            str(exc),
        )
        primary_error: Exception = exc
    except Exception as exc:
        logger.exception(
            "PIPELINE_PRIMARY_ERROR | request_id=%s | step_id=%s | framework=%s | error=%s",
            request_id,
            req.step_id,
            framework,
            exc,
        )
        primary_error = exc

    state_mismatch = _should_stop_for_appium_state_mismatch(
        req=req,
        primary_error=primary_error,
    )
    if state_mismatch is not None:
        logger.info(
            "PIPELINE_STOP_APP_UI_STATE_MISMATCH | request_id=%s | step_id=%s | framework=%s | reason=%s",
            request_id,
            req.step_id,
            framework,
            str(state_mismatch),
        )
        raise state_mismatch

    return await _run_fallback_repair(
        req=req,
        request_id=request_id,
        primary_error=primary_error,
    )


async def _run_primary_repair(
    *,
    req: StepRepairRequest,
    request_id: str,
) -> Tuple[str, str]:
    metrics = get_metrics()
    cir_builder = _get_cir_builder()
    generator = _get_generator()
    verifier = _get_verifier()
    modifier = _get_modifier()
    framework = req.framework

    logger.info(
        "PIPELINE_PRIMARY_START | request_id=%s | step_id=%s | framework=%s",
        request_id,
        req.step_id,
        framework,
    )

    with metrics.repair_pipeline_stage_duration.time(stage="cir_build"):
        block, context = await cir_builder.build(request=req, framework=framework)

    action_type = (
        block.actions[0].action_type
        if getattr(block, "actions", None)
        else "unknown"
    )

    logger.info(
        "PIPELINE_CIR_BUILT | request_id=%s | step_id=%s | framework=%s | block_type=%s | action_type=%s | actions=%d",
        request_id,
        req.step_id,
        framework,
        getattr(block.block_type, "value", str(block.block_type)),
        getattr(action_type, "value", str(action_type)),
        len(getattr(block, "actions", []) or []),
    )

    with metrics.repair_pipeline_stage_duration.time(stage="code_generation"):
        original_lines = (
            context.reference_code.splitlines()
            if getattr(context, "reference_code", None)
            else []
        )
        code_lines: list[str] = []
        for action in block.actions:
            code_lines.extend(
                generator.generate(
                    action,
                    original_lines=original_lines if action.action_type == ActionType.handle_dialog else None,
                    framework=framework,
                )
            )
        candidate_code = "\n".join(code_lines).strip()

    if not candidate_code:
        raise StepNotRepairableError(
            "Primary renderer produced empty code",
            details={"step_id": req.step_id, "framework": framework},
        )

    if block.block_type == CIRBlockType.fallback:
        logger.info(
            "PIPELINE_PRIMARY_FALLBACK_BLOCK | request_id=%s | step_id=%s | framework=%s",
            request_id,
            req.step_id,
            framework,
        )
        return candidate_code, "primary_fallback_block"

    failure_history = [*(req.previous_failed_codes or []), req.original_code]

    with metrics.repair_pipeline_stage_duration.time(stage="verification_1"):
        verdict_1 = await verifier.verify(
            intent=block.intent,
            generated_code=candidate_code,
            matched_script=getattr(context, "matched_script", None),
            error_message=req.error_details.message,
            failure_history=failure_history,
            framework=framework,
        )

    if verdict_1 and verdict_1.get("verdict") == "correct":
        logger.info(
            "PIPELINE_PRIMARY_VERIFIER_SUCCESS | request_id=%s | step_id=%s | framework=%s",
            request_id,
            req.step_id,
            framework,
        )
        return candidate_code, "primary"

    with metrics.repair_pipeline_stage_duration.time(stage="modification"):
        modified_code = await modifier.modify(
            intent=block.intent,
            generated_code=candidate_code,
            verifier_reason=verdict_1.get("reason") if verdict_1 else None,
            failure_history=failure_history,
            error_message=req.error_details.message,
            framework=framework,
        )

    if not modified_code or _normalize_code_for_compare(modified_code) == _normalize_code_for_compare(candidate_code):
        raise StepNotRepairableError(
            "Primary verifier-guided modification produced no meaningful change",
            details={
                "step_id": req.step_id,
                "framework": framework,
                "verifier_reason": verdict_1.get("reason") if verdict_1 else None,
            },
        )

    with metrics.repair_pipeline_stage_duration.time(stage="verification_2"):
        verdict_2 = await verifier.verify(
            intent=block.intent,
            generated_code=modified_code,
            matched_script=getattr(context, "matched_script", None),
            error_message=req.error_details.message,
            failure_history=failure_history,
            framework=framework,
        )

    if verdict_2 and verdict_2.get("verdict") == "correct":
        logger.info(
            "PIPELINE_PRIMARY_MODIFIED_SUCCESS | request_id=%s | step_id=%s | framework=%s",
            request_id,
            req.step_id,
            framework,
        )
        return modified_code, "primary_modified"

    raise StepNotRepairableError(
        "Primary modified code failed verifier hard gate",
        details={
            "step_id": req.step_id,
            "framework": framework,
            "reason": verdict_2.get("reason") if verdict_2 else None,
        },
    )


async def _run_fallback_repair(
    *,
    req: StepRepairRequest,
    request_id: str,
    primary_error: Exception,
) -> Tuple[str, str]:
    from app.services.llm_fallback_repair import LLMFallbackRepairEngine

    framework = req.framework
    logger.info(
        "PIPELINE_FALLBACK_START | request_id=%s | step_id=%s | framework=%s | primary_error=%s",
        request_id,
        req.step_id,
        framework,
        str(primary_error),
    )

    fallback_repair = LLMFallbackRepairEngine()
    fallback_code = await fallback_repair.repair(
        step_intent=req.step_intent,
        current_code=req.original_code,
        error_text=req.artifacts.error_text or "" if req.artifacts else "",
        error_image_bytes=req.artifacts.error_image_bytes if req.artifacts else None,
        dom_snapshot=req.artifacts.dom_snapshot if req.artifacts else None,
        framework=framework,
    )

    if not fallback_code:
        raise StepNotRepairableError(
            f"LLM fallback repair failed for {framework}",
            details={"primary_error": str(primary_error)},
        )

    verifier = StepVerifier(llm=fallback_repair.llm)
    verdict = await verifier.verify(
        intent=req.step_intent,
        generated_code=fallback_code,
        matched_script=None,
        error_message=req.error_details.message,
        failure_history=[*(req.previous_failed_codes or []), req.original_code],
        framework=framework,
    )

    if not verdict or verdict.get("verdict") != "correct":
        raise StepNotRepairableError(
            f"Repair verification failed for {framework}",
            details={
                "primary_error": str(primary_error),
                "fallback_reason": verdict.get("reason") if verdict else "None",
            },
        )

    logger.info(
        "PIPELINE_FALLBACK_SUCCESS | request_id=%s | step_id=%s | framework=%s",
        request_id,
        req.step_id,
        framework,
    )
    return fallback_code, "llm_fallback"


# Backward compatibility alias
repair_pipeline_safe = execute_repair_pipeline
