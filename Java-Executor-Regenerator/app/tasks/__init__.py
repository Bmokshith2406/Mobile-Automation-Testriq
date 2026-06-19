# app/tasks/__init__.py
"""
Celery task queue for background processing.
Enables async repair operations and horizontal scaling.
"""

from app.tasks.celery_app import celery_app
from app.tasks.repair_tasks import (
    repair_step_async,
    execute_script_async,
    batch_repair_steps,
)

__all__ = [
    "celery_app",
    "repair_step_async",
    "execute_script_async",
    "batch_repair_steps",
]
