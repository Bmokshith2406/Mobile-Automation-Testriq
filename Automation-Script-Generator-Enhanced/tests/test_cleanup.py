# tests/test_cleanup.py
"""
Tests for the file cleanup background task (app/core/cleanup.py)

Covers:
- Old files deleted when age > max_age_seconds
- New files preserved when age < max_age_seconds
- Non-existent directory handled gracefully
- Non-file entries (subdirectories) skipped
- Errors on individual files logged but don't crash the loop
- Loop exits cleanly on CancelledError
"""

import asyncio
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.core.cleanup import _delete_old_files, run_cleanup_loop


# ---------------------------------------------------------------------------
# Tests — _delete_old_files (pure logic, synchronous under the hood)
# ---------------------------------------------------------------------------

class TestDeleteOldFiles:

    @pytest.mark.asyncio
    async def test_old_file_is_deleted(self, tmp_path):
        old_file = tmp_path / "test_old.py"
        old_file.write_text("# old")
        # Backdate mtime by 25 hours
        old_mtime = time.time() - (25 * 3600)
        import os
        os.utime(old_file, (old_mtime, old_mtime))

        await _delete_old_files(tmp_path, max_age_seconds=24 * 3600)
        assert not old_file.exists()

    @pytest.mark.asyncio
    async def test_new_file_is_preserved(self, tmp_path):
        new_file = tmp_path / "test_new.py"
        new_file.write_text("# new")

        await _delete_old_files(tmp_path, max_age_seconds=24 * 3600)
        assert new_file.exists()

    @pytest.mark.asyncio
    async def test_nonexistent_directory_handled(self, tmp_path):
        missing = tmp_path / "does_not_exist"
        # Must not raise
        await _delete_old_files(missing, max_age_seconds=3600)

    @pytest.mark.asyncio
    async def test_subdirectories_are_skipped(self, tmp_path):
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        # Backdate the directory
        import os
        old_mtime = time.time() - (25 * 3600)
        os.utime(subdir, (old_mtime, old_mtime))

        await _delete_old_files(tmp_path, max_age_seconds=24 * 3600)
        # Subdirectory must survive (we only delete files)
        assert subdir.exists()

    @pytest.mark.asyncio
    async def test_mixed_ages_only_old_deleted(self, tmp_path):
        import os
        old_file = tmp_path / "test_old.py"
        old_file.write_text("# old")
        old_mtime = time.time() - (48 * 3600)
        os.utime(old_file, (old_mtime, old_mtime))

        new_file = tmp_path / "test_new.py"
        new_file.write_text("# new")

        await _delete_old_files(tmp_path, max_age_seconds=24 * 3600)
        assert not old_file.exists()
        assert new_file.exists()

    @pytest.mark.asyncio
    async def test_permission_error_does_not_crash(self, tmp_path):
        """Individual file errors must be caught and logged, not propagated."""
        problem_file = tmp_path / "problem.py"
        problem_file.write_text("# x")
        import os
        old_mtime = time.time() - (25 * 3600)
        os.utime(problem_file, (old_mtime, old_mtime))

        with patch.object(Path, "unlink", side_effect=PermissionError("no permission")):
            # Must NOT raise
            await _delete_old_files(tmp_path, max_age_seconds=24 * 3600)


# ---------------------------------------------------------------------------
# Tests — run_cleanup_loop lifecycle
# ---------------------------------------------------------------------------

class TestCleanupLoop:

    @pytest.mark.asyncio
    async def test_loop_exits_on_cancelled_error(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "a" * 32)
        monkeypatch.setenv("CLEANUP_ENABLED", "true")
        monkeypatch.setenv("CLEANUP_MAX_AGE_HOURS", "24")

        task = asyncio.create_task(run_cleanup_loop())
        await asyncio.sleep(0.01)
        task.cancel()
        # Should not raise — CancelledError must be swallowed gracefully
        await asyncio.gather(task, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_loop_exits_immediately_when_disabled(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "a" * 32)
        monkeypatch.setenv("CLEANUP_ENABLED", "false")
        # run_cleanup_loop should return quickly when disabled
        await asyncio.wait_for(run_cleanup_loop(), timeout=2.0)
