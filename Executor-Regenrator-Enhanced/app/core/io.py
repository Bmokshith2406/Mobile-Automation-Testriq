from __future__ import annotations
import os
import tempfile
import json
from pathlib import Path
from datetime import datetime, UTC

class AtomicWriter:
    @staticmethod
    def write(path: Path, content: str, encoding: str = "utf-8"):
        path.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.NamedTemporaryFile(
            "w",
            delete=False,
            encoding=encoding,
            dir=str(path.parent),
        ) as tmp:
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = Path(tmp.name)

        tmp_path.replace(path)


class FailureArtifactWriter:
    @staticmethod
    def write(
        *,
        root: Path,
        test_case: str,
        reason: dict,
        stdout: str | None = None,
        stderr: str | None = None,
        diff: str | None = None,
        screenshot: bytes | None = None,
    ):
        base = root / "failed_runs" / test_case
        base.mkdir(parents=True, exist_ok=True)

        ts = datetime.now(UTC).isoformat()

        (base / "failure_reason.json").write_text(
            json.dumps({"timestamp": ts, **reason}, indent=2),
            encoding="utf-8",
        )

        if stdout:
            (base / "last_stdout.txt").write_text(stdout, encoding="utf-8")

        if stderr:
            (base / "last_stderr.txt").write_text(stderr, encoding="utf-8")

        if diff:
            (base / "patch_diff.txt").write_text(diff, encoding="utf-8")

        if screenshot:
            (base / "screenshot.png").write_bytes(screenshot)
