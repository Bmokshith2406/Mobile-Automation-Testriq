from __future__ import annotations

import ast
import asyncio
import json
import shutil
import logging
from pathlib import Path
from typing import Dict, Optional, List, Tuple
from datetime import datetime, UTC
from dataclasses import dataclass, field, replace, is_dataclass

from app.executors import AsyncPythonExecutor
from app.services.auto_repair_trigger import AutoRepairTrigger
from app.services.repair_service import RepairService
from app.services.repair_explanation_service import RepairExplanationService
from app.core.exceptions import StepNotRepairableError
from app.services.script_patcher import ScriptPatcher
from app.services.framework_classifier import FrameworkClassifier
from app.core.config import settings

# Safety & Resilience components from new locations
from app.core.resilience import CircuitBreaker, BackoffPolicy
from app.core.utils import FailureFingerprint
from app.core.io import AtomicWriter
from app.services.rollback import RollbackManager

logger = logging.getLogger("execution.orchestrator.self_healing")


# ==================================================
# CONFIG
# ==================================================

@dataclass
class ExecutorOrchestratorConfig:
    max_repairs_per_step: int = 5
    repair_timeout_sec: int = 200
    max_running_retries: int = 3
    artifacts_root: Path = Path.cwd()
    status_filename: str = "status.txt"


# ==================================================
# CONTEXT
# ==================================================

@dataclass
class ExecutionContext:
    repair_attempts: Dict[str, int] = field(default_factory=dict)
    repair_history: List[dict] = field(default_factory=list)
    failure_fingerprints: Dict[str, int] = field(default_factory=dict)
    running_retries: int = 0
    created_run_dirs: List[str] = field(default_factory=list)


# ==================================================
# ORCHESTRATOR
# ==================================================

class SelfHealingExecutorOrchestrator:
    VALID_STATUSES = {"passed", "failed", "running"}

    def __init__(
        self,
        *,
        executor: AsyncPythonExecutor,
        repair_trigger: AutoRepairTrigger,
        repair_service: RepairService,
        patcher: ScriptPatcher,
        config: ExecutorOrchestratorConfig = ExecutorOrchestratorConfig(),
    ):
        self.executor = executor
        self.repair_trigger = repair_trigger
        self.repair_service = repair_service
        self.patcher = patcher
        self.config = config

        self.circuit_breaker = CircuitBreaker()
        self.backoff = BackoffPolicy()
        self.rollback_manager = RollbackManager()
        self.framework_classifier = FrameworkClassifier()
        self._explainer: Optional[RepairExplanationService] = None

    # ==================================================
    # PUBLIC API
    # ==================================================

    @property
    def explainer(self) -> RepairExplanationService:
        if self._explainer is None:
            self._explainer = RepairExplanationService()
        return self._explainer

    async def execute_script_with_self_healing(
        self,
        *,
        script_path: str,
        extra_env: Optional[Dict[str, str]] = None,
        framework_override: Optional[str] = None,
    ):
        ctx = ExecutionContext()
        iteration = 0

        framework = (framework_override or "").strip().lower()
        if framework in {"playwright", "selenium", "cypress", "appium"}:
            logger.warning(
                "framework_route_selected | framework=%s | script_path=%s",
                framework.upper(),
                script_path,
            )
        else:
            # Backward-compatible fallback for internal callers that have not
            # yet been routed through a framework-specific endpoint.
            framework = await self.framework_classifier.classify_framework(script_path)
            logger.warning(
                "framework_auto_detected | framework=%s | script_path=%s",
                framework.upper(),
                script_path,
            )

        self._warn_guarded_step_source_mismatches(
            script_path=script_path,
            framework=framework,
        )

        while True:
            iteration += 1
            logger.info("EXECUTION_START", extra={"iteration": iteration})

            # --------------------------------------------------
            # ALWAYS RE-EXECUTE SCRIPT EACH ITERATION
            # --------------------------------------------------

            result = await asyncio.wait_for(
                self.executor.execute(script_path, extra_env=extra_env),
                timeout=settings.EXECUTOR_TIMEOUT_SECONDS
            )

            if result.working_dir:
                ctx.created_run_dirs.append(result.working_dir)

            status, execution_dir = self._resolve_execution_status(
                result.artifacts_dir
            )

            # ----------------------------
            # STATUS MUST BE VALID
            # ----------------------------

            if status is None:
                logger.error("STATUS_RESOLUTION_FAILED_FATAL")
                return self._finalize_result(result, ctx, "failed")

            if status == "running":
                ctx.running_retries += 1

                if ctx.running_retries > self.config.max_running_retries:
                    logger.error("RUNNING_STATUS_STUCK_ABORTING")
                    return self._finalize_result(result, ctx, "failed", script_path=script_path, execution_dir=execution_dir, iteration=iteration)

                logger.info("STATUS_RUNNING_REEXECUTING", extra={"iteration": iteration})
                await asyncio.sleep(1)
                continue

            # ----------------------------
            # PASSED → FINALIZE
            # ----------------------------

            if status == "passed":
                self._mark_pending_repairs_after_rerun(ctx, passed=True)
                if execution_dir:
                    self._emit_final_docs(
                        script_path=script_path,
                        execution_dir=execution_dir,
                        iterations=iteration,
                        final_status="passed",
                        ctx=ctx,
                    )
                return self._finalize_result(result, ctx, "passed")

            # ----------------------------
            # FAILED → TRY REPAIR
            # ----------------------------

            repair_request = await asyncio.to_thread(
                self.repair_trigger.build_request_from_artifacts,
                result.artifacts_dir,
            )

            if not repair_request:
                logger.error("NO_REPAIR_REQUEST_STOPPING")
                return self._finalize_result(result, ctx, "failed", script_path=script_path, execution_dir=execution_dir, iteration=iteration)

            repair_request.framework = framework

            step_id = repair_request.step_id

            # Update the outcome of the previous repair for this step to rerun_failed
            # because the script failed on the same step again.
            for item in reversed(ctx.repair_history):
                if item.get("step_id") == step_id:
                    if item.get("outcome") in {"patched", "llm_verified"}:
                        item["outcome"] = "rerun_failed"
                        self._mark_explanation_rerun(item, passed=False)
                    break

            attempt = self._increment_attempt(ctx, step_id)

            if attempt > self.config.max_repairs_per_step:
                logger.error("MAX_REPAIRS_PER_STEP_EXCEEDED", extra={"step_id": step_id})
                self._record_repair(ctx, step_id, attempt, "permanent_failure")
                await self._handle_final_failure(result, repair_request, ctx)
                return self._finalize_result(result, ctx, "failed", script_path=script_path, execution_dir=execution_dir, iteration=iteration)

            fingerprint = FailureFingerprint.compute(
                step_id,
                result.stderr or "",
                result.stdout or "",
            )

            count = ctx.failure_fingerprints.get(fingerprint, 0) + 1
            ctx.failure_fingerprints[fingerprint] = count

            if count > 2:
                logger.error(
                    "REPEATED_FAILURE_ABORT",
                    extra={"step_id": step_id, "fingerprint": fingerprint, "count": count},
                )
                self._record_repair(ctx, step_id, attempt, "permanent_failure")
                await self._handle_final_failure(result, repair_request, ctx)
                return self._finalize_result(result, ctx, "failed", script_path=script_path, execution_dir=execution_dir, iteration=iteration)

            if not self.circuit_breaker.allow():
                logger.error("CIRCUIT_BREAKER_OPEN")
                self._record_repair(ctx, step_id, attempt, "permanent_failure")
                await self._handle_final_failure(result, repair_request, ctx)
                return self._finalize_result(result, ctx, "failed", script_path=script_path, execution_dir=execution_dir, iteration=iteration)

            try:
                repaired_code, repair_action = await asyncio.wait_for(
                    self.repair_service.repair_step(
                        request=repair_request,
                        error_image_bytes=repair_request.artifacts.error_image_bytes,
                        request_id=result.run_id,
                    ),
                    timeout=self.config.repair_timeout_sec,
                )
                self.circuit_breaker.record_success()

            except StepNotRepairableError as exc:
                self.circuit_breaker.record_failure()
                logger.warning(
                    "REPAIR_PIPELINE_NOT_REPAIRABLE",
                    extra={"step_id": step_id, "reason": str(exc)},
                )
                self._record_repair(ctx, step_id, attempt, "permanent_failure")
                await self._handle_final_failure(result, repair_request, ctx)
                return self._finalize_result(result, ctx, "failed", script_path=script_path, execution_dir=execution_dir, iteration=iteration)

            except asyncio.TimeoutError:
                self.circuit_breaker.record_failure()
                delay = self.backoff.compute(attempt)
                await asyncio.sleep(delay)
                continue

            except Exception:
                self.circuit_breaker.record_failure()
                logger.exception("REPAIR_API_FAILURE")
                delay = self.backoff.compute(attempt)
                await asyncio.sleep(delay)
                continue

            if not repaired_code:
                logger.error("EMPTY_REPAIR_RESPONSE_FATAL")
                return self._finalize_result(result, ctx, "failed", script_path=script_path, execution_dir=execution_dir, iteration=iteration)

            step_fn = self._extract_step_function(step_id)
            if not step_fn:
                logger.error("INVALID_STEP_ID_FORMAT")
                return self._finalize_result(result, ctx, "failed", script_path=script_path, execution_dir=execution_dir, iteration=iteration)

            # ----------------------------
            # APPLY PATCH
            # ----------------------------

            backup_path = self.patcher.patch_step(
                script_path=script_path,
                step_function_name=step_fn,
                new_step_body=repaired_code,
                backup=True,
            )

            self.rollback_manager.register(step_id, backup_path)

            # ----------------------------------------
            # Generate explanation
            # ----------------------------------------
            explanation = await self.explainer.generate_explanation(
                step_id=step_id,
                step_intent=repair_request.step_intent,
                original_code=repair_request.original_code,
                repaired_code=repaired_code,
                error_text=repair_request.artifacts.error_text or "",
                dom_snapshot=repair_request.artifacts.dom_snapshot,
                error_image_bytes=repair_request.artifacts.error_image_bytes,
                framework=framework,
            )

            self._record_repair(
                ctx,
                step_id,
                attempt,
                "patched",
                explanation=explanation,
                repair_action=repair_action,
            )

            delay = self.backoff.compute(attempt)
            await asyncio.sleep(delay)

            # 🔁 CRITICAL: RE-RUN SCRIPT AFTER PATCH
            continue

    async def execute_with_self_healing(
        self,
        *,
        script_path: str,
        extra_env: Optional[Dict[str, str]] = None,
        framework_override: Optional[str] = None,
    ):
        """Backward compatibility wrapper."""
        return await self.execute_script_with_self_healing(
            script_path=script_path,
            extra_env=extra_env,
            framework_override=framework_override,
        )

    async def _handle_final_failure(
        self,
        result,
        repair_request,
        ctx: ExecutionContext,
    ):
        step_id = repair_request.step_id
        logger.info("GENERATING_FINAL_FAILURE_EXPLANATION | step_id=%s", step_id)

        try:
            explanation = await self.explainer.generate_explanation(
                step_id=step_id,
                step_intent=repair_request.step_intent,
                original_code=repair_request.original_code,
                repaired_code="PERMANENT_FAILURE (Self-healing attempts exhausted)",
                error_text=repair_request.artifacts.error_text or "",
                dom_snapshot=repair_request.artifacts.dom_snapshot,
                error_image_bytes=repair_request.artifacts.error_image_bytes,
                framework=repair_request.framework,
            )

            if explanation:
                explanation["rerun_result"] = "failed"
                explanation["execution_passed"] = False
                if not hasattr(result, "metadata") or result.metadata is None:
                    result.metadata = {}
                result.metadata["final_failure_explanation"] = explanation

                # Write to execution_dir if resolved, otherwise working_dir
                _, execution_dir = self._resolve_execution_status(result.artifacts_dir)
                if execution_dir:
                    explanation_path = execution_dir / "final_failure_explanation.json"
                else:
                    explanation_path = Path(result.working_dir) / "final_failure_explanation.json"

                AtomicWriter.write(
                    explanation_path,
                    json.dumps(explanation, indent=2),
                )
                logger.info("Saved final_failure_explanation.json to %s", explanation_path)
        except Exception as e:
            logger.warning("Failed to generate/save final failure explanation: %s", e)

    # ==================================================
    # CONTEXT OPS
    # ==================================================

    def _increment_attempt(self, ctx: ExecutionContext, step_id: str) -> int:
        ctx.repair_attempts[step_id] = ctx.repair_attempts.get(step_id, 0) + 1
        return ctx.repair_attempts[step_id]

    def _record_repair(
        self,
        ctx: ExecutionContext,
        step_id: str,
        attempt: int,
        outcome: str,
        explanation: Optional[dict] = None,
        repair_action: Optional[str] = None,
    ):
        if isinstance(explanation, dict):
            explanation.setdefault("rerun_result", "pending_rerun")
            explanation.setdefault("execution_passed", None)
        ctx.repair_history.append(
            {
                "step_id": step_id,
                "attempt": attempt,
                "outcome": outcome,
                "repair_action": repair_action,
                "verification_outcome": "llm_verified" if outcome == "patched" else None,
                "explanation": explanation,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

    def _mark_pending_repairs_after_rerun(
        self,
        ctx: ExecutionContext,
        *,
        passed: bool,
    ) -> None:
        for item in reversed(ctx.repair_history):
            if item.get("outcome") in {"patched", "llm_verified"}:
                item["outcome"] = "rerun_passed" if passed else "rerun_failed"
                self._mark_explanation_rerun(item, passed=passed)
                return

    @staticmethod
    def _mark_explanation_rerun(item: dict, *, passed: bool) -> None:
        explanation = item.get("explanation")
        if not isinstance(explanation, dict):
            return
        explanation["rerun_result"] = "passed" if passed else "failed"
        explanation["execution_passed"] = passed

    @staticmethod
    def _preview_text(value: Optional[str], limit: int = 500) -> str:
        text = (value or "").strip()
        if len(text) <= limit:
            return text
        return f"{text[:limit]}... [truncated]"

    def _warn_guarded_step_source_mismatches(
        self,
        *,
        script_path: str,
        framework: str,
    ) -> None:
        """
        Generated scripts carry executable step functions and a source-code
        string inside _guarded_step(...). If those diverge, repair prompts can
        describe code that is not actually executed.
        """
        try:
            source = Path(script_path).read_text(encoding="utf-8")
            tree = ast.parse(source)
        except Exception as exc:
            logger.debug(
                "SCRIPT_SOURCE_MISMATCH_SCAN_SKIPPED | framework=%s | error=%s",
                framework,
                exc,
            )
            return

        lines = source.splitlines(keepends=True)
        functions = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "_guarded_step":
                continue

            step_fn_node = node.args[1] if len(node.args) > 1 else None
            step_code_node = node.args[4] if len(node.args) > 4 else None
            step_id_node = node.args[2] if len(node.args) > 2 else None

            if not isinstance(step_fn_node, ast.Name):
                continue
            if not isinstance(step_code_node, ast.Constant) or not isinstance(step_code_node.value, str):
                continue

            fn_node = functions.get(step_fn_node.id)
            if not fn_node or not fn_node.body:
                continue

            body_text = self._function_body_source(lines, fn_node)
            guarded_text = step_code_node.value
            if self._normalize_step_source(body_text) == self._normalize_step_source(guarded_text):
                continue

            step_id = (
                step_id_node.value
                if isinstance(step_id_node, ast.Constant) and isinstance(step_id_node.value, str)
                else step_fn_node.id
            )
            logger.warning(
                "SCRIPT_SOURCE_MISMATCH | framework=%s | step_id=%s | step_fn=%s | "
                "function_preview=%r | guarded_preview=%r",
                framework,
                step_id,
                step_fn_node.id,
                self._preview_text(body_text, 160),
                self._preview_text(guarded_text, 160),
            )

    @staticmethod
    def _function_body_source(lines: List[str], node: ast.AST) -> str:
        body = getattr(node, "body", None) or []
        if not body:
            return ""
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

    # ==================================================
    # RESULT REHYDRATION
    # ==================================================

    @staticmethod
    def _with_semantic_status(result, semantic_status: str):
        assert semantic_status in {"passed", "failed"}

        if is_dataclass(result):
            return replace(result, semantic_status=semantic_status)

        try:
            setattr(result, "semantic_status", semantic_status)
            return result
        except Exception:
            return result

    def _finalize_result(
        self,
        result,
        ctx: ExecutionContext,
        semantic_status: str,
        script_path: Optional[str] = None,
        execution_dir: Optional[Path] = None,
        iteration: int = 1,
    ):
        if semantic_status == "failed" and script_path and execution_dir:
            try:
                self._emit_final_docs(
                    script_path=script_path,
                    execution_dir=execution_dir,
                    iterations=iteration,
                    final_status="failed",
                    ctx=ctx,
                )
            except Exception as e:
                logger.warning("Failed to emit final documents for failed run: %s", e)

        finalized = self._with_semantic_status(result, semantic_status)

        try:
            metadata = dict(getattr(finalized, "metadata", {}) or {})
            metadata["repairs_attempted"] = len(ctx.repair_history)
            metadata["repairs_successful"] = sum(
                1
                for item in ctx.repair_history
                if item.get("outcome") == "rerun_passed"
            )
            metadata["repair_history"] = ctx.repair_history
            metadata["created_run_dirs"] = ctx.created_run_dirs
            finalized.metadata = metadata
        except Exception:
            logger.debug("Unable to attach execution metadata", exc_info=True)

        return finalized

    # ==================================================
    # STATUS RESOLUTION
    # ==================================================

    def _resolve_execution_status(
        self, artifacts_dir: Optional[str]
    ) -> Tuple[Optional[str], Optional[Path]]:

        if not artifacts_dir:
            logger.error("STATUS_RESOLUTION_FAILED: artifacts_dir is None")
            return None, None

        base = Path(artifacts_dir).resolve()

        logger.info(
            "STATUS_SEARCH_START",
            extra={
                "artifacts_dir_input": artifacts_dir,
                "resolved_base": str(base),
                "status_filename": self.config.status_filename,
            },
        )

        if not base.exists():
            logger.error(
                "STATUS_SEARCH_BASE_NOT_FOUND",
                extra={"resolved_base": str(base)},
            )
            return None, None

        logger.info(
            "STATUS_SEARCH_WALKING_TREE",
            extra={"search_root": str(base)},
        )

        status_files = list(base.rglob(self.config.status_filename))

        logger.info(
            "STATUS_SEARCH_RESULTS",
            extra={
                "count": len(status_files),
                "paths": [str(p) for p in status_files],
            },
        )

        if not status_files:
            logger.error("STATUS_FILE_NOT_FOUND", extra={"search_root": str(base)})
            return None, None

        status_file = max(status_files, key=lambda p: p.stat().st_mtime)

        logger.info(
            "STATUS_FILE_SELECTED",
            extra={"path": str(status_file)},
        )

        value = status_file.read_text(encoding="utf-8").strip().lower()

        logger.info(
            "STATUS_FILE_READ",
            extra={"value": value, "path": str(status_file)},
        )

        if value not in self.VALID_STATUSES:
            logger.error(
                "INVALID_STATUS",
                extra={"value": value, "file": str(status_file)},
            )
            return None, None

        logger.info(
            "STATUS_RESOLVED",
            extra={"value": value, "path": str(status_file)},
        )

        return value, status_file.parent

    # ==================================================
    # SUCCESS ARTIFACTS
    # ==================================================

    def _emit_final_docs(
        self,
        *,
        script_path: str,
        execution_dir: Path,
        iterations: int,
        final_status: str,
        ctx: ExecutionContext,
    ):
        # --------------------------------------------------
        # Derive execution folder name
        # --------------------------------------------------
        execution_id = execution_dir.name

        root = self.config.artifacts_root
        if final_status == "passed":
            target_root = root / "successful_runs"
        else:
            target_root = root / "failed_runs"

        target_dir = target_root / execution_id
        target_dir.mkdir(parents=True, exist_ok=True)

        # --------------------------------------------------
        # Copy ENTIRE execution directory
        # --------------------------------------------------
        for item in execution_dir.iterdir():
            dest = target_dir / item.name

            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)

        # --------------------------------------------------
        # Write final healed script
        # --------------------------------------------------
        AtomicWriter.write(
            target_dir / "final_script.py",
            Path(script_path).read_text(encoding="utf-8"),
        )

        # --------------------------------------------------
        # Write repair report
        # --------------------------------------------------
        report = {
            "final_status": final_status,
            "iterations": iterations,
            "repairs": ctx.repair_history,
            "execution_id": execution_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        AtomicWriter.write(
            target_dir / "repair_report.json",
            json.dumps(report, indent=2),
        )

    # ==================================================
    # UTILS
    # ==================================================

    @staticmethod
    def _extract_step_function(step_id: str) -> Optional[str]:
        if "__" not in step_id:
            return None
        return step_id.split("__", 1)[1]


# Backward compatibility aliases
OrchestratorConfig = ExecutorOrchestratorConfig
ExecutionOrchestratorV2_1 = SelfHealingExecutorOrchestrator
