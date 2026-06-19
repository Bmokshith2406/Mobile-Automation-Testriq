# app/tasks/celery_app.py
"""
Celery application configuration.

This module stays importable even when Celery is not installed so the rest of
the service can boot without background-worker dependencies.
"""

from __future__ import annotations

from typing import Any, Callable

from app.core.config import settings

try:
    from celery import Celery
    from kombu import Exchange, Queue

    CELERY_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised in dependency-light environments
    Celery = None
    Exchange = None
    Queue = None
    CELERY_AVAILABLE = False


class _FallbackTask:
    abstract = True

    def __call__(self, *args, **kwargs):
        raise RuntimeError("Celery is not installed in this environment")


class _FallbackCeleryApp:
    Task = _FallbackTask

    def __init__(self):
        self.conf: dict[str, Any] = {}

    def task(self, *args, **kwargs):
        def decorator(func: Callable):
            return func

        return decorator


if CELERY_AVAILABLE:
    celery_app = Celery(
        "repair_engine",
        broker=settings.celery.broker_url,
        backend=settings.celery.result_backend,
        include=[
            "app.tasks.repair_tasks",
        ],
    )

    celery_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        task_time_limit=settings.celery.task_time_limit,
        task_soft_time_limit=settings.celery.task_soft_time_limit,
        worker_prefetch_multiplier=settings.celery.worker_prefetch_multiplier,
        worker_concurrency=settings.celery.worker_concurrency,
        worker_max_tasks_per_child=1000,
        result_expires=3600,
        result_extended=True,
        task_default_retry_delay=5,
        task_max_retries=3,
        beat_schedule={
            "cleanup-old-fingerprints": {
                "task": "app.tasks.repair_tasks.cleanup_old_fingerprints",
                "schedule": 3600.0,
            },
            "collect-metrics": {
                "task": "app.tasks.repair_tasks.collect_metrics",
                "schedule": 60.0,
            },
        },
        task_routes={
            "app.tasks.repair_tasks.repair_step_async": {"queue": "repair"},
            "app.tasks.repair_tasks.execute_script_async": {"queue": "execution"},
            "app.tasks.repair_tasks.batch_repair_steps": {"queue": "batch"},
            "app.tasks.repair_tasks.cleanup_old_fingerprints": {"queue": "maintenance"},
            "app.tasks.repair_tasks.collect_metrics": {"queue": "maintenance"},
        },
        task_queues=(
            Queue("repair", Exchange("repair"), routing_key="repair", queue_arguments={"x-max-priority": 10}),
            Queue("execution", Exchange("execution"), routing_key="execution", queue_arguments={"x-max-priority": 10}),
            Queue("batch", Exchange("batch"), routing_key="batch"),
            Queue("maintenance", Exchange("maintenance"), routing_key="maintenance"),
        ),
        task_default_queue="repair",
        task_default_exchange="repair",
        task_default_routing_key="repair",
    )

    class BaseTask(celery_app.Task):
        abstract = True

        def on_success(self, retval, task_id, args, kwargs):
            return None

        def on_failure(self, exc, task_id, args, kwargs, einfo):
            from app.core.metrics import get_metrics

            get_metrics().self_healing_attempts_total.inc(
                outcome=f"celery_failure:{type(exc).__name__}",
            )

        def on_retry(self, exc, task_id, args, kwargs, einfo):
            from app.core.metrics import get_metrics

            get_metrics().self_healing_attempts_total.inc(
                outcome="celery_retry",
            )

    celery_app.Task = BaseTask
else:
    celery_app = _FallbackCeleryApp()


__all__ = ["CELERY_AVAILABLE", "celery_app"]
