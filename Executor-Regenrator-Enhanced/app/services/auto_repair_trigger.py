from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional
from datetime import datetime, UTC

from app.models.step_repair import (
    StepRepairRequest,
    Artifacts,
    ErrorClassification,
    ErrorDetails,
)

logger = logging.getLogger("auto_repair.trigger")


class AutoRepairTrigger:
    """
    Converts execution failure artifacts into a rich StepRepairRequest.

    Handles:
    - Executor artifact paths (runs/<id>/artifacts)
    - Generator artifact paths (cwd/artifacts/<test>/<run>)
    - Mutable summary.json states (running → failed)
    - Cross-process file visibility delays
    """

    SUMMARY_RETRY_COUNT = 20
    SUMMARY_RETRY_DELAY_SEC = 0.1

    # ==================================================
    # PUBLIC API
    # ==================================================

    def build_request_from_artifacts(
        self,
        artifacts_dir: str,
    ) -> Optional[StepRepairRequest]:

        logger.info(
            "AUTO-REPAIR TRIGGER INVOKED | artifacts_dir=%s",
            artifacts_dir,
        )

        artifacts_dir = Path(artifacts_dir)

        # --------------------------------------------------
        # Resolve failures directory
        # --------------------------------------------------

        failures_dir = self._resolve_failures_dir(artifacts_dir)
        if failures_dir is None:
            logger.info(
                "AUTO-REPAIR SKIPPED | reason=failures_dir_not_found",
            )
            return None
        
        # --------------------------------------------------
        # Check authoritative status.txt first
        # --------------------------------------------------

        status_file = failures_dir.parent / "status.txt"

        if not status_file.exists():
            logger.info(
                "AUTO-REPAIR SKIPPED | reason=status_file_missing"
            )
            return None

        status_value = status_file.read_text(encoding="utf-8").strip().lower()

        logger.info(
            "AUTO-REPAIR STATUS FILE READ | value=%s",
            status_value,
        )

        if status_value != "failed":
            logger.info(
                "AUTO-REPAIR SKIPPED | reason=status_not_failed | value=%s",
                status_value,
            )
            return None

        # --------------------------------------------------
        # Load summary.json
        # --------------------------------------------------

        summary = self._load_summary(failures_dir)
        if summary is None:
            logger.info(
                "AUTO-REPAIR SKIPPED | reason=summary_unavailable | path=%s",
                failures_dir,
            )
            return None

        status = summary.get("status")
        failed_index = summary.get("failed_step_index")

        logger.info(
            "AUTO-REPAIR SUMMARY | status=%s | failed_step_index=%s",
            status,
            failed_index,
        )

        if status != "failed":
            logger.info(
                "AUTO-REPAIR SKIPPED | reason=summary_not_final",
            )
            return None

        if not isinstance(failed_index, int):
            logger.info(
                "AUTO-REPAIR SKIPPED | reason=invalid_failed_step_index",
            )
            return None

        # --------------------------------------------------
        # Locate failed step directory
        # --------------------------------------------------

        step_dir = self._find_step_dir(
            failures_dir,
            failed_index,
            summary.get("failed_device_slug"),
        )
        if not step_dir:
            logger.warning(
                "AUTO-REPAIR SKIPPED | reason=step_dir_not_found | index=%s",
                failed_index,
            )
            return None

        # --------------------------------------------------
        # Resolve LATEST attempt directory
        # --------------------------------------------------

        attempt_dir = self._latest_attempt_dir(step_dir)
        if not attempt_dir:
            logger.warning(
                "AUTO-REPAIR SKIPPED | reason=no_attempt_dirs | step_id=%s",
                step_dir.name,
            )
            return None

        logger.info(
            "AUTO-REPAIR STEP IDENTIFIED | step_id=%s | attempt=%s",
            step_dir.name,
            attempt_dir.name,
        )

        # --------------------------------------------------
        # Mandatory files
        # --------------------------------------------------

        step_code_path = attempt_dir / "step_code.py"
        intent_path = attempt_dir / "intent.txt"

        if not step_code_path.exists() or not intent_path.exists():
            logger.warning(
                "AUTO-REPAIR SKIPPED | reason=missing_mandatory_files | step_id=%s",
                step_dir.name,
            )
            return None

        step_code = step_code_path.read_text(encoding="utf-8").strip()
        intent = intent_path.read_text(encoding="utf-8").strip()
        device_context = self._read_optional_json(attempt_dir / "device_context.json")

        if not step_code or not intent:
            logger.warning(
                "AUTO-REPAIR SKIPPED | reason=empty_code_or_intent | step_id=%s",
                step_dir.name,
            )
            return None

        if device_context:
            intent = self._augment_intent_with_device_context(intent, device_context)

        # --------------------------------------------------
        # Error details
        # --------------------------------------------------

        error_text = self._read_optional(attempt_dir / "error.txt")
        traceback_text = self._read_optional(attempt_dir / "traceback.txt")

        error_message = error_text.strip() if (error_text and error_text.strip()) else "Unknown runtime error"
        error_details = ErrorDetails(
            message=error_message,
            failed_api=self._infer_failed_api(error_text),
            timestamp=datetime.now(UTC).isoformat(),
        )

        error_type = self._classify_error(error_text, traceback_text)
        error_classification = ErrorClassification(
            type=error_type
        )

        logger.info(
            "AUTO-REPAIR ERROR CLASSIFIED | step_id=%s | type=%s",
            step_dir.name,
            error_classification.type,
        )

        # --------------------------------------------------
        # Artifacts
        # --------------------------------------------------

        artifacts = Artifacts(
            error_image_bytes=self._read_optional_bytes(
                attempt_dir / "screenshot.png"
            ),
            dom_snapshot=(
                self._read_optional(attempt_dir / "dom.html")
                or self._read_optional(attempt_dir / "dom.xml")
            ),
            error_text=error_text,
            traceback_text=traceback_text,
        )

        # --------------------------------------------------
        # Final repair request
        # --------------------------------------------------

        previous_failed_codes = self._collect_previous_failed_codes(step_dir)
        
        request = StepRepairRequest(
            step_id=step_dir.name,
            step_intent=intent,
            original_code=step_code,
            error_classification=error_classification,
            error_details=error_details,
            traceback=traceback_text,
            artifacts=artifacts,
            previous_failed_codes=previous_failed_codes or None,
        )

        logger.info(
            "AUTO-REPAIR REQUEST BUILT | step_id=%s | attempt=%s",
            step_dir.name,
            attempt_dir.name,
        )

        return request

    # ==================================================
    # INTERNAL HELPERS
    # ==================================================

    def _collect_previous_failed_codes(self, step_dir: Path) -> list[str]:
        """
        Collect all previous failed attempt codes (excluding latest).
        Returns list in chronological order.
        """

        attempts = sorted(
            [
                d for d in step_dir.iterdir()
                if d.is_dir() and d.name.startswith("attempt_")
            ],
            key=lambda p: p.stat().st_mtime,
        )

        if len(attempts) <= 1:
            return []

        previous_attempts = attempts[:-1]  # exclude latest

        history: list[str] = []

        for attempt in previous_attempts:
            step_code_path = attempt / "step_code.py"
            if step_code_path.exists():
                code = step_code_path.read_text(encoding="utf-8").strip()
                if code:
                    history.append(code)

        return history
    
    @staticmethod
    def _resolve_failures_dir(artifacts_dir: Path) -> Optional[Path]:
        """
        Resolve failures directory within SAME run scope only.
        """

        direct = artifacts_dir / "failures"
        if direct.exists():
            return direct

        run_root = artifacts_dir.parent
        if not run_root.exists():
            return None

        candidates = sorted(
            run_root.glob("**/failures/summary.json"),
            key=lambda p: p.stat().st_mtime,
        )

        if not candidates:
            return None

        resolved = candidates[-1].parent
        logger.info(
            "AUTO-REPAIR FAILURES DIR RESOLVED | %s",
            resolved,
        )
        return resolved

    def _load_summary(self, failures_dir: Path) -> Optional[dict]:
        path = failures_dir / "summary.json"

        for attempt in range(self.SUMMARY_RETRY_COUNT):
            if path.exists():
                try:
                    summary = json.loads(path.read_text(encoding="utf-8"))

                    # Wait until summary reaches terminal state
                    if summary.get("status") in {"failed", "passed"}:
                        return summary

                except json.JSONDecodeError:
                    logger.debug(
                        "SUMMARY READ RETRY | attempt=%d",
                        attempt + 1,
                    )

            time.sleep(self.SUMMARY_RETRY_DELAY_SEC)

        return None

    @staticmethod
    def _find_step_dir(
        failures_dir: Path,
        index: int,
        device_slug: Optional[str] = None,
    ) -> Optional[Path]:
        search_roots = []
        if device_slug:
            device_root = failures_dir / str(device_slug)
            if device_root.exists():
                search_roots.append(device_root)
        search_roots.append(failures_dir)

        for root in search_roots:
            for d in root.iterdir():
                if d.is_dir() and d.name.startswith(f"{index}_"):
                    return d

        for d in failures_dir.rglob("*"):
            if d.is_dir() and d.name.startswith(f"{index}_"):
                return d
        return None

    @staticmethod
    def _latest_attempt_dir(step_dir: Path) -> Optional[Path]:
        attempts = sorted(
            [d for d in step_dir.iterdir() if d.is_dir() and d.name.startswith("attempt_")],
            key=lambda p: p.stat().st_mtime,
        )
        return attempts[-1] if attempts else None

    @staticmethod
    def _read_optional(path: Path) -> Optional[str]:
        return path.read_text(encoding="utf-8") if path.exists() else None

    @staticmethod
    def _read_optional_bytes(path: Path) -> Optional[bytes]:
        return path.read_bytes() if path.exists() else None

    @staticmethod
    def _read_optional_json(path: Path) -> Optional[dict]:
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except Exception:
            logger.debug("Failed to read optional JSON artifact: %s", path, exc_info=True)
            return None

    @staticmethod
    def _augment_intent_with_device_context(intent: str, device_context: dict) -> str:
        label = device_context.get("label") or device_context.get("slug")
        platform = device_context.get("platform_name")
        device_name = device_context.get("device_name")
        app_package = device_context.get("app_package")
        bundle_id = device_context.get("bundle_id")

        parts = []
        if label:
            parts.append(f"device_label={label}")
        if device_name:
            parts.append(f"device_name={device_name}")
        if platform:
            parts.append(f"platform={platform}")
        if app_package:
            parts.append(f"app_package={app_package}")
        if bundle_id:
            parts.append(f"bundle_id={bundle_id}")

        if not parts:
            return intent

        return f"[Appium device context: {'; '.join(parts)}]\n{intent}"

    @staticmethod
    def _infer_failed_api(error_text: Optional[str]) -> Optional[str]:
        if not error_text:
            return None
        if "find_element" in error_text:
            return "driver.find_element"
        if "wait_for_selector" in error_text:
            return "page.wait_for_selector"
        if "to_be_visible" in error_text:
            return "expect.to_be_visible"
        return None

    @staticmethod
    def _classify_error(
        error_text: Optional[str],
        traceback_text: Optional[str],
    ) -> str:
        if error_text and "Timeout" in error_text:
            return "ASSERTION_TIMEOUT"
        if error_text and "AssertionError" in error_text:
            return "ASSERTION_FAILURE"
        if traceback_text:
            return "RUNTIME_EXCEPTION"
        return "UNCLASSIFIED"
