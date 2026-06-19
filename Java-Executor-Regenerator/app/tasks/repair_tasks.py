# app/tasks/repair_tasks.py
"""
Celery tasks for async repair operations.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, UTC
import logging
import asyncio
from pathlib import Path

from app.tasks.celery_app import celery_app
from app.core.config import settings
from app.core.utils import set_correlation_id

logger = logging.getLogger(__name__)


# ==============================================================================
# ASYNC HELPER
# ==============================================================================

def run_async(coro):
    """Run async coroutine in sync context."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ==============================================================================
# REPAIR TASKS
# ==============================================================================

@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=5,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    name="app.tasks.repair_tasks.repair_step_async",
)
def repair_step_async(
    self,
    step_id: str,
    step_intent: str,
    original_code: str,
    error_type: str,
    error_message: str,
    screenshot_base64: Optional[str] = None,
    dom_snapshot: Optional[str] = None,
    correlation_id: Optional[str] = None,
    priority: int = 5,
) -> Dict[str, Any]:
    """
    Async task for repairing a single step.
    
    Args:
        step_id: Unique identifier for the step
        step_intent: Natural language description of what the step does
        original_code: The original failing code
        error_type: Classification of the error
        error_message: Detailed error message
        screenshot_base64: Optional screenshot for visual analysis
        dom_snapshot: Optional DOM snapshot
        correlation_id: Request correlation ID for tracing
        priority: Task priority (1-10, higher = more priority)
    
    Returns:
        Dict containing repair result
    """
    from app.core.base64_utils import normalize_base64
    from app.core.exceptions import StepNotRepairableError
    from app.models.step_repair import (
        Artifacts,
        StepRepairRequest,
        ErrorClassification,
        ErrorDetails,
    )
    from app.core.database import get_repository, RepairRecord
    from app.core.metrics import get_metrics
    from app.services.repair_pipeline import repair_pipeline_safe
    
    start_time = datetime.now(UTC)
    request_meta = getattr(self, "request", None)
    task_id = getattr(request_meta, "id", None) or f"repair-{datetime.now(UTC).timestamp()}"
    retry_count = getattr(request_meta, "retries", 0)
    metrics = get_metrics()
    set_correlation_id(correlation_id)
    
    logger.info(
        f"Starting async repair task",
        extra={
            "task_id": task_id,
            "step_id": step_id,
            "correlation_id": correlation_id,
            "attempt": retry_count + 1,
        }
    )
    
    try:
        screenshot_bytes = normalize_base64(screenshot_base64) if screenshot_base64 else None
        request = StepRepairRequest(
            step_id=step_id,
            step_intent=step_intent,
            original_code=original_code,
            error_classification=ErrorClassification(type=error_type),
            error_details=ErrorDetails(message=error_message),
            artifacts=Artifacts(
                dom_snapshot=dom_snapshot,
            ),
        )
        
        async def _repair():
            repaired_code, action_type = await repair_pipeline_safe(
                request=request,
                error_image_bytes=screenshot_bytes,
                request_id=correlation_id or task_id,
            )
            return {
                "generated_code": repaired_code,
                "action_type": action_type,
            }

        try:
            result = run_async(_repair())
            is_valid = True
            outcome = "success"
        except StepNotRepairableError as exc:
            result = {
                "generated_code": None,
                "action_type": "unknown",
            }
            is_valid = False
            outcome = "not_repairable"
            logger.info(
                "Repair task determined step is not repairable",
                extra={
                    "task_id": task_id,
                    "step_id": step_id,
                    "reason": str(exc),
                },
            )
        
        duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
        
        # Record to database
        async def _record():
            repo = await get_repository()
            record = RepairRecord(
                step_id=step_id,
                original_code=original_code,
                repaired_code=result["generated_code"],
                intent=step_intent,
                error_type=error_type,
                error_message=error_message,
                outcome=outcome,
                duration_ms=duration_ms,
                model_name=settings.LLM_MODEL_NAME,
                request_id=correlation_id,
                metadata={
                    "task_id": task_id,
                    "attempts": retry_count + 1,
                }
            )
            await repo.save_repair(record)
        
        run_async(_record())
        
        # Record metrics
        metrics.repair_requests_total.inc(
            outcome=outcome,
            action_type=result["action_type"] or "unknown",
        )
        
        logger.info(
            f"Repair task completed successfully",
            extra={
                "task_id": task_id,
                "step_id": step_id,
                "duration_ms": duration_ms,
                "is_valid": is_valid,
            }
        )
        
        return {
            "status": outcome,
            "step_id": step_id,
            "task_id": task_id,
            "generated_code": result["generated_code"],
            "is_valid": is_valid,
            "duration_ms": duration_ms,
        }
        
    except Exception as e:
        logger.error(
            f"Repair task failed",
            extra={
                "task_id": task_id,
                "step_id": step_id,
                "error": str(e),
                "attempt": retry_count + 1,
            },
            exc_info=True
        )
        
        # Record failure
        duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
        metrics.repair_requests_total.inc(
            outcome="failure",
            action_type="unknown",
        )
        
        raise


@celery_app.task(
    bind=True,
    max_retries=2,
    default_retry_delay=10,
    name="app.tasks.repair_tasks.execute_script_async",
)
def execute_script_async(
    self,
    script_path: str,
    enable_self_healing: bool = True,
    max_repair_attempts: int = 3,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Async task for executing a script with self-healing.
    
    Args:
        script_path: Path to the script to execute
        enable_self_healing: Whether to enable self-healing repairs
        max_repair_attempts: Maximum repair attempts per step
        correlation_id: Request correlation ID for tracing
    
    Returns:
        Dict containing execution result
    """
    from app.executors import SandboxedPythonExecutor
    from app.core.database import get_repository, ExecutionRecord
    from app.core.metrics import get_metrics
    
    start_time = datetime.now(UTC)
    request_meta = getattr(self, "request", None)
    task_id = getattr(request_meta, "id", None) or f"execute-{datetime.now(UTC).timestamp()}"
    metrics = get_metrics()
    set_correlation_id(correlation_id)
    
    logger.info(
        f"Starting async execution task",
        extra={
            "task_id": task_id,
            "script_path": script_path,
            "correlation_id": correlation_id,
        }
    )
    
    try:
        # Execute script
        async def _execute():
            executor = SandboxedPythonExecutor()
            return await executor.execute_sandboxed(
                script_content=Path(script_path).read_text(encoding="utf-8"),
            )
        
        result = run_async(_execute())
        
        duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
        
        # Determine status
        status = result.semantic_status
        
        # Record to database
        async def _record():
            repo = await get_repository()
            metadata = getattr(result, "metadata", {}) or {}
            record = ExecutionRecord(
                run_id=task_id,
                script_path=script_path,
                status=status,
                exit_code=result.exit_code,
                duration_ms=duration_ms,
                stdout=result.stdout[:10000] if result.stdout else None,
                stderr=result.stderr[:10000] if result.stderr else None,
                repairs_attempted=metadata.get("repairs_attempted", 0),
                repairs_successful=metadata.get("repairs_successful", 0),
                request_id=correlation_id,
                metadata={
                    "task_id": task_id,
                    "self_healing_enabled": enable_self_healing,
                    "step_results": getattr(result, "step_results", None),
                    "execution_outcome": getattr(getattr(result, "outcome", None), "value", None),
                    "error": getattr(result, "error", None),
                }
            )
            await repo.save_execution(record)
        
        run_async(_record())
        
        # Record metrics
        metrics.script_executions_total.inc(status=status)
        
        logger.info(
            f"Execution task completed",
            extra={
                "task_id": task_id,
                "script_path": script_path,
                "status": status,
                "duration_ms": duration_ms,
            }
        )
        
        return {
            "status": status,
            "task_id": task_id,
            "script_path": script_path,
            "duration_ms": duration_ms,
            **result.to_dict(),
        }
        
    except Exception as e:
        logger.error(
            f"Execution task failed",
            extra={
                "task_id": task_id,
                "script_path": script_path,
                "error": str(e),
            },
            exc_info=True
        )
        raise


@celery_app.task(
    bind=True,
    max_retries=1,
    name="app.tasks.repair_tasks.batch_repair_steps",
)
def batch_repair_steps(
    self,
    steps: List[Dict[str, Any]],
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Batch repair multiple steps.
    
    Args:
        steps: List of step repair requests
        correlation_id: Request correlation ID
    
    Returns:
        Dict containing batch repair results
    """
    try:
        from celery import group
    except ImportError as exc:  # pragma: no cover - depends on optional celery install
        raise RuntimeError("Celery is not installed in this environment") from exc
    
    request_meta = getattr(self, "request", None)
    task_id = getattr(request_meta, "id", None) or f"batch-{datetime.now(UTC).timestamp()}"
    set_correlation_id(correlation_id)
    
    logger.info(
        f"Starting batch repair task",
        extra={
            "task_id": task_id,
            "step_count": len(steps),
            "correlation_id": correlation_id,
        }
    )
    
    # Create group of repair tasks
    repair_tasks = group(
        repair_step_async.s(
            step_id=step["step_id"],
            step_intent=step["step_intent"],
            original_code=step["original_code"],
            error_type=step["error_type"],
            error_message=step["error_message"],
            screenshot_base64=step.get("screenshot_base64"),
            dom_snapshot=step.get("dom_snapshot"),
            correlation_id=correlation_id,
        )
        for step in steps
    )
    
    # Execute group and wait for results
    result = repair_tasks.apply_async()
    results = result.get(timeout=300)  # 5 minute timeout
    
    # Summarize results
    successful = sum(1 for r in results if r.get("status") == "success")
    failed = len(results) - successful
    
    return {
        "status": "completed",
        "task_id": task_id,
        "total_steps": len(steps),
        "successful": successful,
        "failed": failed,
        "results": results,
    }


# ==============================================================================
# MAINTENANCE TASKS
# ==============================================================================

@celery_app.task(name="app.tasks.repair_tasks.cleanup_old_fingerprints")
def cleanup_old_fingerprints() -> Dict[str, Any]:
    """
    Periodic task to clean up old failure fingerprints.
    """
    from app.core.redis_state import FailureFingerprintCache
    
    logger.info("Starting fingerprint cleanup task")
    
    async def _cleanup():
        cache = await FailureFingerprintCache.create()
        fingerprints = await cache.get_all_fingerprints()
        
        # For now, just log the count
        # In production, implement age-based cleanup
        return len(fingerprints)
    
    count = run_async(_cleanup())
    
    logger.info(f"Fingerprint cleanup completed, {count} fingerprints in cache")
    
    return {
        "status": "completed",
        "fingerprint_count": count,
    }


@celery_app.task(name="app.tasks.repair_tasks.collect_metrics")
def collect_metrics() -> Dict[str, Any]:
    """
    Periodic task to collect and export metrics.
    """
    logger.debug("Collecting metrics")
    
    async def _collect():
        from app.core.database import get_repository
        repo = await get_repository()
        
        repair_stats = await repo.get_repair_stats()
        execution_stats = await repo.get_execution_stats()
        
        return {
            "repair_stats": repair_stats,
            "execution_stats": execution_stats,
        }
    
    stats = run_async(_collect())
    
    return {
        "status": "completed",
        "timestamp": datetime.now(UTC).isoformat(),
        **stats,
    }
