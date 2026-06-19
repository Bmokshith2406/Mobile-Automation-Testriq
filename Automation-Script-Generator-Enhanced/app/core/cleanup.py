# app/core/cleanup.py
"""
Background File Cleanup Task

Periodically deletes generated script files older than CLEANUP_MAX_AGE_HOURS
from the outputs directory. Runs as a long-lived asyncio background task
started in the application lifespan context.

Controlled by:
    CLEANUP_ENABLED       (bool)  — toggle, default True
    CLEANUP_MAX_AGE_HOURS (int)   — max file age before deletion, default 24
"""

import asyncio
import logging
import time
from pathlib import Path

logger = logging.getLogger("cleanup")

# How often (seconds) to scan the directory. 1-hour interval is enough
# for a 24-hour max-age policy; adjust if you lower max age significantly.
_SCAN_INTERVAL_SECONDS = 3600


def _get_output_dir() -> Path:
    """Resolve the default output directory relative to this file's location."""
    return Path(__file__).resolve().parents[2] / "outputs" / "generated_scripts"


async def _delete_old_files(output_dir: Path, max_age_seconds: float) -> None:
    """Delete files in output_dir whose mtime is older than max_age_seconds."""
    if not output_dir.exists():
        return

    now = time.time()
    deleted = 0
    errors = 0

    for entry in output_dir.iterdir():
        if not entry.is_file():
            continue
        try:
            age_seconds = now - entry.stat().st_mtime
            if age_seconds > max_age_seconds:
                entry.unlink(missing_ok=True)
                deleted += 1
                logger.debug("Deleted old script | path=%s | age_hours=%.1f", entry, age_seconds / 3600)
        except Exception:
            errors += 1
            logger.exception("Could not delete file | path=%s", entry)

    if deleted or errors:
        logger.info(
            "Cleanup cycle complete | deleted=%d | errors=%d | dir=%s",
            deleted, errors, output_dir,
        )


async def run_cleanup_loop(output_dir: Path | None = None) -> None:
    """
    Infinite loop that runs cleanup every _SCAN_INTERVAL_SECONDS.

    Designed to be launched as an asyncio Task from the lifespan context:

        cleanup_task = asyncio.create_task(run_cleanup_loop())

    Cancel it on shutdown:

        cleanup_task.cancel()
        await asyncio.gather(cleanup_task, return_exceptions=True)
    """
    from app.core.config import get_settings
    settings = get_settings()

    if not settings.CLEANUP_ENABLED:
        logger.info("File cleanup is disabled (CLEANUP_ENABLED=false)")
        return

    target_dir = output_dir or _get_output_dir()
    max_age_seconds = settings.CLEANUP_MAX_AGE_HOURS * 3600

    logger.info(
        "Cleanup task started | dir=%s | max_age_hours=%d | interval_s=%d",
        target_dir, settings.CLEANUP_MAX_AGE_HOURS, _SCAN_INTERVAL_SECONDS,
    )

    while True:
        try:
            # Sleep first so startup is not delayed by a scan
            await asyncio.sleep(_SCAN_INTERVAL_SECONDS)
            await _delete_old_files(target_dir, max_age_seconds)
        except asyncio.CancelledError:
            logger.info("Cleanup task cancelled — shutting down")
            break
        except Exception:
            # Never let an unexpected error kill the background task
            logger.exception("Cleanup task encountered an error (will retry next cycle)")
