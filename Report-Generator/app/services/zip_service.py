import json
import mimetypes
import re
import zipfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable, Optional

from fastapi import UploadFile

from app.core.config import get_settings
from app.core.errors import APIException, ErrorCategory, ErrorCode, ErrorSeverity
from app.core.logger import get_logger
from app.models.domain import ArtifactBinary, Artifacts, ReportData, ReportMetadata, StepExecution, StepSummary


settings = get_settings()
logger = get_logger(__name__)


@dataclass(frozen=True)
class ArchiveEntry:
    path: str
    normalized_path: str
    info: zipfile.ZipInfo

    @property
    def filename(self) -> str:
        return PurePosixPath(self.path).name

    @property
    def parent(self) -> str:
        return str(PurePosixPath(self.path).parent)


class ArchiveCatalog:
    def __init__(self, zip_ref: zipfile.ZipFile):
        self.zip_ref = zip_ref
        self.entries: dict[str, ArchiveEntry] = {}
        self._validate_and_index()

    def _validate_and_index(self) -> None:
        infos = [info for info in self.zip_ref.infolist() if not info.is_dir()]

        if len(infos) > settings.MAX_ZIP_ENTRIES:
            raise APIException(
                error_code=ErrorCode.INVALID_ZIP,
                message=f"ZIP contains too many entries (max {settings.MAX_ZIP_ENTRIES})",
                status_code=400,
                category=ErrorCategory.VALIDATION,
                severity=ErrorSeverity.ERROR,
            )

        total_uncompressed = sum(info.file_size for info in infos)
        if total_uncompressed > settings.MAX_DECOMPRESSED_SIZE_BYTES:
            raise APIException(
                error_code=ErrorCode.INVALID_ZIP,
                message="ZIP archive expands beyond the allowed decompressed size",
                status_code=413,
                category=ErrorCategory.VALIDATION,
                severity=ErrorSeverity.ERROR,
            )

        for info in infos:
            normalized = self._normalize_path(info.filename)

            if normalized in self.entries:
                raise APIException(
                    error_code=ErrorCode.INVALID_ZIP,
                    message=f"ZIP contains duplicate entries for '{normalized}'",
                    status_code=400,
                    category=ErrorCategory.VALIDATION,
                    severity=ErrorSeverity.ERROR,
                )

            compression_ratio = info.file_size / max(info.compress_size, 1)
            if info.file_size > 1024 and compression_ratio > settings.MAX_COMPRESSION_RATIO:
                raise APIException(
                    error_code=ErrorCode.INVALID_ZIP,
                    message=f"ZIP entry '{normalized}' exceeds the allowed compression ratio",
                    status_code=400,
                    category=ErrorCategory.VALIDATION,
                    severity=ErrorSeverity.ERROR,
                )

            self.entries[normalized] = ArchiveEntry(
                path=info.filename,
                normalized_path=normalized,
                info=info,
            )

    def _normalize_path(self, path: str) -> str:
        sanitized = path.replace("\\", "/").strip("/")
        pure = PurePosixPath(sanitized)

        if pure.is_absolute() or any(part in {"..", ""} for part in pure.parts):
            raise APIException(
                error_code=ErrorCode.INVALID_ZIP,
                message=f"ZIP contains unsafe path '{path}'",
                status_code=400,
                category=ErrorCategory.VALIDATION,
                severity=ErrorSeverity.ERROR,
            )

        return str(pure).lower()

    def find_exact(self, *paths: str) -> Optional[ArchiveEntry]:
        for path in paths:
            normalized = self._normalize_path(path)
            entry = self.entries.get(normalized)
            if entry is not None:
                return entry
        return None

    def find_first(self, predicate) -> Optional[ArchiveEntry]:
        for entry in self.entries.values():
            if predicate(entry):
                return entry
        return None

    def find_children(self, parent: str, filenames: Iterable[str]) -> Optional[ArchiveEntry]:
        normalized_parent = self._normalize_path(parent)
        filename_set = {name.lower() for name in filenames}

        for entry in self.entries.values():
            if entry.parent.lower() == normalized_parent and entry.filename.lower() in filename_set:
                return entry
        return None

    def parent_dirs_for(self, filename: str) -> list[str]:
        normalized_filename = filename.lower()
        parents = {
            entry.parent
            for entry in self.entries.values()
            if entry.filename.lower() == normalized_filename and entry.parent not in {".", "/"}
        }
        return sorted(parents)

    def parent_dirs_for_predicate(self, predicate) -> list[str]:
        parents = {
            entry.parent
            for entry in self.entries.values()
            if predicate(entry) and entry.parent not in {".", "/"}
        }
        return sorted(parents)

    def read_bytes(self, entry: ArchiveEntry, *, max_bytes: Optional[int] = None) -> bytes:
        if max_bytes is not None and entry.info.file_size > max_bytes:
            raise APIException(
                error_code=ErrorCode.INVALID_ZIP,
                message=f"ZIP entry '{entry.path}' exceeds the allowed size",
                status_code=400,
                category=ErrorCategory.VALIDATION,
                severity=ErrorSeverity.ERROR,
            )
        return self.zip_ref.read(entry.path)

    def read_text(self, entry: ArchiveEntry, *, max_bytes: Optional[int] = None) -> str:
        return self.read_bytes(entry, max_bytes=max_bytes).decode("utf-8", errors="ignore")

    def read_json(self, entry: ArchiveEntry, *, max_bytes: Optional[int] = None) -> dict:
        try:
            return json.loads(self.read_text(entry, max_bytes=max_bytes))
        except json.JSONDecodeError as exc:
            raise APIException(
                error_code=ErrorCode.VALIDATION_ERROR,
                message=f"Invalid JSON in '{entry.path}'",
                status_code=400,
                category=ErrorCategory.VALIDATION,
                severity=ErrorSeverity.ERROR,
                details={"error": str(exc)},
            ) from exc


class BaseArtifactParser(ABC):
    format_name = "unknown"

    def __init__(self, catalog: ArchiveCatalog, upload_file: UploadFile):
        self.catalog = catalog
        self.upload_file = upload_file

    @classmethod
    @abstractmethod
    def matches(cls, catalog: ArchiveCatalog) -> bool:
        raise NotImplementedError

    @abstractmethod
    def parse(self) -> ReportData:
        raise NotImplementedError

    def _extract_required_script(self) -> tuple[str, str]:
        script_entry = self.catalog.find_exact("final_script.py", "generated_script.py")
        if script_entry is None:
            raise APIException(
                error_code=ErrorCode.MISSING_ARTIFACTS,
                message="Missing required artifact 'final_script.py'",
                status_code=400,
                category=ErrorCategory.VALIDATION,
                severity=ErrorSeverity.ERROR,
            )
        script_text = self.catalog.read_text(script_entry, max_bytes=settings.MAX_SCRIPT_SIZE_BYTES)
        if not script_text.strip():
            raise APIException(
                error_code=ErrorCode.MISSING_ARTIFACTS,
                message="'final_script.py' is empty",
                status_code=400,
                category=ErrorCategory.VALIDATION,
                severity=ErrorSeverity.ERROR,
            )
        return script_text, script_entry.filename

    def _extract_optional_video(self) -> Optional[ArtifactBinary]:
        video_entry = self.catalog.find_first(
            lambda entry: entry.filename.lower().endswith((".webm", ".mp4"))
            and "screenshot" not in entry.filename.lower()
        )
        if video_entry is None:
            return None

        video_data = self.catalog.read_bytes(video_entry, max_bytes=settings.MAX_VIDEO_SIZE_BYTES)
        media_type = self._detect_media_type(video_entry.filename, default="application/octet-stream")
        return ArtifactBinary(
            filename=video_entry.filename,
            media_type=media_type,
            data=video_data,
            size_bytes=len(video_data),
        )

    def _extract_optional_repair_report(self) -> Optional[dict]:
        repair_entry = self.catalog.find_exact("repair_report.json")
        if repair_entry is None:
            return None
        return self.catalog.read_json(repair_entry, max_bytes=settings.MAX_SCRIPT_SIZE_BYTES)

    def _extract_screenshot(self, step_dir: str) -> Optional[ArtifactBinary]:
        screenshot_entry = self.catalog.find_children(
            step_dir,
            filenames=("screenshot.png", "screenshot.jpg", "screenshot.jpeg", "screenshot.webp"),
        )
        if screenshot_entry is None:
            return None

        screenshot_data = self.catalog.read_bytes(
            screenshot_entry,
            max_bytes=settings.MAX_SCREENSHOT_SIZE_BYTES,
        )
        media_type = self._detect_media_type(screenshot_entry.filename, default="image/png")
        return ArtifactBinary(
            filename=screenshot_entry.filename,
            media_type=media_type,
            data=screenshot_data,
            size_bytes=len(screenshot_data),
        )

    def _build_step(
        self,
        *,
        step_dir: str,
        summary_data: dict,
        fallback_index: int,
        source_path: str,
    ) -> StepExecution:
        step_index = self._extract_step_index(step_dir, summary_data, fallback_index)
        return StepExecution(
            summary=StepSummary(
                step_index=step_index,
                step_name=str(summary_data.get("step_name") or PurePosixPath(step_dir).name),
                intent=str(summary_data.get("intent") or summary_data.get("step_name") or "").strip(),
                status=summary_data.get("status", "unknown"),
                duration_sec=float(summary_data.get("duration_sec") or 0.0),
                attempts=int(summary_data.get("attempts") or 0),
                max_retries=int(summary_data.get("max_retries") or 0),
                url=str(summary_data.get("url") or "").strip(),
            ),
            screenshot=self._extract_screenshot(step_dir),
            execution_timestamp=summary_data.get("started_at")
            or summary_data.get("execution_timestamp")
            or summary_data.get("ended_at"),
            source_path=source_path,
        )

    def _extract_step_index(self, step_dir: str, summary_data: dict, fallback_index: int) -> int:
        raw_index = summary_data.get("step_index")
        if raw_index is None:
            derived = self._derive_index_from_path(step_dir)
            return derived if derived is not None else fallback_index

        try:
            parsed = int(raw_index)
        except (TypeError, ValueError) as exc:
            raise APIException(
                error_code=ErrorCode.VALIDATION_ERROR,
                message=f"Invalid step_index in '{step_dir}'",
                status_code=400,
                category=ErrorCategory.VALIDATION,
                severity=ErrorSeverity.ERROR,
                details={"error": str(exc)},
            ) from exc

        derived = self._derive_index_from_path(step_dir)
        if derived is not None and parsed != derived:
            raise APIException(
                error_code=ErrorCode.VALIDATION_ERROR,
                message=f"Step index mismatch between directory '{step_dir}' and summary.json",
                status_code=400,
                category=ErrorCategory.VALIDATION,
                severity=ErrorSeverity.ERROR,
            )

        return parsed

    def _derive_index_from_path(self, step_dir: str) -> Optional[int]:
        basename = PurePosixPath(step_dir).name
        match = re.match(r"(?P<index>\d+)(__|$)", basename)
        if match:
            return int(match.group("index"))

        generic_match = re.search(r"step[-_](?P<index>\d+)", basename.lower())
        if generic_match:
            return int(generic_match.group("index"))

        return None

    def _validate_step_collection(self, steps: list[StepExecution]) -> list[StepExecution]:
        if not steps:
            raise APIException(
                error_code=ErrorCode.MISSING_ARTIFACTS,
                message="ZIP does not contain any step summaries",
                status_code=400,
                category=ErrorCategory.VALIDATION,
                severity=ErrorSeverity.ERROR,
            )

        if len(steps) > settings.MAX_STEP_COUNT:
            raise APIException(
                error_code=ErrorCode.INVALID_ZIP,
                message=f"ZIP contains too many steps (max {settings.MAX_STEP_COUNT})",
                status_code=400,
                category=ErrorCategory.VALIDATION,
                severity=ErrorSeverity.ERROR,
            )

        seen_indices: set[int] = set()
        for step in steps:
            if step.summary.step_index in seen_indices:
                raise APIException(
                    error_code=ErrorCode.VALIDATION_ERROR,
                    message="ZIP contains duplicate step_index values",
                    status_code=400,
                    category=ErrorCategory.VALIDATION,
                    severity=ErrorSeverity.ERROR,
                )
            seen_indices.add(step.summary.step_index)

        return sorted(steps, key=lambda step: step.summary.step_index)

    def _detect_media_type(self, filename: str, *, default: str) -> str:
        guessed, _ = mimetypes.guess_type(filename)
        return guessed or default


class MatrixBundleArtifactParser(BaseArtifactParser):
    format_name = "appium_matrix"

    @classmethod
    def matches(cls, catalog: ArchiveCatalog) -> bool:
        return (
            catalog.find_exact("matrix_summary.json") is not None
            and any(
                entry.normalized_path.count("/") >= 1
                and entry.normalized_path.endswith("/final_script.py")
                for entry in catalog.entries.values()
            )
        )

    def parse(self) -> ReportData:
        testcase_name = self.upload_file.filename.replace(".zip", "") if self.upload_file.filename else "Appium Matrix"
        matrix_entry = self.catalog.find_exact("matrix_summary.json")
        matrix_payload = self.catalog.read_json(matrix_entry, max_bytes=settings.MAX_SCRIPT_SIZE_BYTES) if matrix_entry else {}
        testcase_name = str(matrix_payload.get("test_case_id") or matrix_payload.get("name") or testcase_name)

        prefixes = self._run_prefixes(matrix_payload)
        device_labels = self._device_labels_from_summary(matrix_payload)
        scripts: list[str] = []
        repair_reports: dict[str, dict] = {}
        steps: list[StepExecution] = []
        started_at = None
        finished_at = None
        final_failure_explanation = None

        for prefix in prefixes:
            device_label = device_labels.get(prefix, prefix)
            started_at = started_at or self._read_optional_prefixed_text(prefix, "started_at.txt")
            finished_at = self._read_optional_prefixed_text(prefix, "finished_at.txt") or finished_at

            script_entry = self.catalog.find_exact(f"{prefix}/final_script.py", f"{prefix}/generated_script.py")
            if script_entry is not None:
                script_text = self.catalog.read_text(script_entry, max_bytes=settings.MAX_SCRIPT_SIZE_BYTES)
                scripts.append(f"# ==== {device_label} ({prefix}) ====\n{script_text}")

            repair_entry = self.catalog.find_exact(f"{prefix}/repair_report.json")
            if repair_entry is not None:
                repair_reports[prefix] = self.catalog.read_json(repair_entry, max_bytes=settings.MAX_SCRIPT_SIZE_BYTES)

            explanation_entry = self.catalog.find_exact(f"{prefix}/final_failure_explanation.json")
            if explanation_entry is not None and final_failure_explanation is None:
                final_failure_explanation = self.catalog.read_json(
                    explanation_entry,
                    max_bytes=settings.MAX_SCRIPT_SIZE_BYTES,
                )

            summary_entry = self.catalog.find_exact(
                f"{prefix}/success/summary.json",
                f"{prefix}/failures/summary.json",
            )
            if summary_entry is not None:
                summary_payload = self.catalog.read_json(summary_entry, max_bytes=settings.MAX_SCRIPT_SIZE_BYTES)
                testcase_name = str(summary_payload.get("test_case_id") or testcase_name)
                for step_metric in summary_payload.get("steps", []):
                    steps.append(
                        self._build_matrix_step_from_metric(
                            prefix=prefix,
                            device_label=device_label,
                            step_metric=step_metric,
                            global_index=len(steps),
                        )
                    )
                continue

            step_dirs = [
                step_dir
                for step_dir in self.catalog.parent_dirs_for("step_summary.json")
                if step_dir.lower().startswith(f"{prefix}/")
            ]
            for step_dir in step_dirs:
                summary_entry = self.catalog.find_exact(f"{step_dir}/step_summary.json")
                if summary_entry is None:
                    continue
                summary_data = self.catalog.read_json(summary_entry, max_bytes=settings.MAX_SCRIPT_SIZE_BYTES)
                steps.append(
                    self._build_matrix_step_from_summary(
                        step_dir=step_dir,
                        summary_data=summary_data,
                        device_label=device_label,
                        global_index=len(steps),
                        source_path=summary_entry.path,
                    )
                )

        if not scripts:
            raise APIException(
                error_code=ErrorCode.MISSING_ARTIFACTS,
                message="Missing required artifact 'final_script.py' in matrix run folders",
                status_code=400,
                category=ErrorCategory.VALIDATION,
                severity=ErrorSeverity.ERROR,
            )

        video = self._extract_optional_video()
        repair_report = {
            "matrix_summary": matrix_payload,
            "runs": repair_reports,
        }

        return ReportData(
            metadata=ReportMetadata(
                testcase_name=testcase_name,
                started_at=started_at,
                finished_at=finished_at,
                source_format=self.format_name,
            ),
            steps=self._validate_step_collection(steps),
            artifacts=Artifacts(
                execution_video=video,
                final_script="\n\n".join(scripts),
                final_script_filename="matrix_final_scripts.py",
                repair_report=repair_report,
            ),
            final_failure_explanation=final_failure_explanation,
        )

    def _run_prefixes(self, matrix_payload: Optional[dict] = None) -> list[str]:
        prefixes = {
            entry.normalized_path.split("/", 1)[0]
            for entry in self.catalog.entries.values()
            if entry.normalized_path.endswith("/final_script.py")
            or entry.normalized_path.endswith("/generated_script.py")
        }
        ordered: list[str] = []
        for run in (matrix_payload or {}).get("runs", []) or []:
            if not isinstance(run, dict):
                continue
            folder = str(run.get("folder") or run.get("slug") or "").lower()
            if folder in prefixes and folder not in ordered:
                ordered.append(folder)
        ordered.extend(sorted(prefixes - set(ordered)))
        return ordered

    def _device_labels_from_summary(self, matrix_payload: dict) -> dict[str, str]:
        labels: dict[str, str] = {}
        for run in matrix_payload.get("runs", []) or []:
            if not isinstance(run, dict):
                continue
            folder = str(run.get("folder") or run.get("slug") or "").lower()
            device = run.get("device") if isinstance(run.get("device"), dict) else {}
            label = device.get("label") or run.get("label") or folder
            if folder:
                labels[folder] = str(label)
        return labels

    def _read_optional_prefixed_text(self, prefix: str, filename: str) -> Optional[str]:
        entry = self.catalog.find_exact(f"{prefix}/{filename}")
        if entry is None:
            return None
        return self.catalog.read_text(entry, max_bytes=2 * 1024 * 1024).strip() or None

    def _build_matrix_step_from_metric(
        self,
        *,
        prefix: str,
        device_label: str,
        step_metric: dict,
        global_index: int,
    ) -> StepExecution:
        step_name = str(step_metric.get("step_name") or f"step_{step_metric.get('step_index', global_index)}")
        status = str(step_metric.get("status") or "unknown")

        if status == "passed":
            summary_dirs = self.catalog.parent_dirs_for_predicate(
                lambda entry: entry.filename.lower() == "step_summary.json"
                and entry.normalized_path.startswith(f"{prefix}/")
                and step_name.lower() in entry.normalized_path
            )
            if summary_dirs:
                summary_entry = self.catalog.find_exact(f"{summary_dirs[0]}/step_summary.json")
                summary_data = self.catalog.read_json(summary_entry, max_bytes=settings.MAX_SCRIPT_SIZE_BYTES)
                return self._build_matrix_step_from_summary(
                    step_dir=summary_dirs[0],
                    summary_data=summary_data,
                    device_label=device_label,
                    global_index=global_index,
                    source_path=summary_entry.path,
                )

            return self._matrix_step(
                global_index=global_index,
                device_label=device_label,
                step_name=step_name,
                intent=str(step_metric.get("intent") or step_name),
                status="passed",
                duration_sec=float(step_metric.get("duration_total_sec") or 0.0),
                attempts=int(step_metric.get("attempts") or 1),
                max_retries=int(step_metric.get("max_retries") or 0),
            )

        attempt_prefix = self._latest_attempt_prefix(prefix, step_name)
        intent = ""
        intent_entry = self.catalog.find_exact(f"{attempt_prefix}/intent.txt")
        if intent_entry:
            intent = self.catalog.read_text(intent_entry, max_bytes=10 * 1024 * 1024).strip()

        error_msg = ""
        error_entry = self.catalog.find_exact(f"{attempt_prefix}/error.txt")
        if error_entry:
            error_msg = self.catalog.read_text(error_entry, max_bytes=10 * 1024 * 1024).strip()
            if len(error_msg) > 10000:
                error_msg = error_msg[:10000] + "\n... [truncated]"

        screenshot = None
        screenshot_entry = self.catalog.find_exact(f"{attempt_prefix}/screenshot.png")
        if screenshot_entry:
            screenshot_data = self.catalog.read_bytes(screenshot_entry, max_bytes=settings.MAX_SCREENSHOT_SIZE_BYTES)
            screenshot = ArtifactBinary(
                filename=screenshot_entry.filename,
                media_type=self._detect_media_type(screenshot_entry.filename, default="image/png"),
                data=screenshot_data,
                size_bytes=len(screenshot_data),
            )

        latest_attempt_match = re.search(r"attempt_(\d+)$", attempt_prefix)
        latest_attempt = int(latest_attempt_match.group(1)) if latest_attempt_match else 1

        return self._matrix_step(
            global_index=global_index,
            device_label=device_label,
            step_name=step_name,
            intent=intent or str(step_metric.get("intent") or step_name),
            status="failed",
            duration_sec=float(step_metric.get("duration_total_sec") or 0.0),
            attempts=int(step_metric.get("attempts") or latest_attempt),
            max_retries=int(step_metric.get("max_retries") or 0),
            screenshot=screenshot,
            ai_summary=error_msg or "Step failed execution.",
            source_path=f"{attempt_prefix}/step_code.py",
        )

    def _build_matrix_step_from_summary(
        self,
        *,
        step_dir: str,
        summary_data: dict,
        device_label: str,
        global_index: int,
        source_path: str,
    ) -> StepExecution:
        return self._matrix_step(
            global_index=global_index,
            device_label=device_label,
            step_name=str(summary_data.get("step_name") or PurePosixPath(step_dir).name),
            intent=str(summary_data.get("intent") or summary_data.get("step_name") or "").strip(),
            status=summary_data.get("status", "unknown"),
            duration_sec=float(summary_data.get("duration_sec") or summary_data.get("duration_total_sec") or 0.0),
            attempts=int(summary_data.get("attempts") or 0),
            max_retries=int(summary_data.get("max_retries") or 0),
            screenshot=self._extract_screenshot(step_dir),
            execution_timestamp=summary_data.get("started_at")
            or summary_data.get("execution_timestamp")
            or summary_data.get("ended_at"),
            source_path=source_path,
        )

    def _latest_attempt_prefix(self, prefix: str, step_name: str) -> str:
        latest_attempt = 1
        attempt_prefix = f"{prefix}/failures/{step_name}/attempt_1"
        for entry in self.catalog.entries.values():
            path = entry.normalized_path
            if not path.startswith(f"{prefix}/") or "/failures/" not in path or step_name.lower() not in path:
                continue
            match = re.search(r"attempt_(\d+)", path)
            if match:
                attempt = int(match.group(1))
                if attempt >= latest_attempt:
                    latest_attempt = attempt
                    marker = f"attempt_{attempt}"
                    attempt_prefix = path[: path.index(marker) + len(marker)]
        return attempt_prefix

    def _matrix_step(
        self,
        *,
        global_index: int,
        device_label: str,
        step_name: str,
        intent: str,
        status: str,
        duration_sec: float,
        attempts: int,
        max_retries: int,
        screenshot: Optional[ArtifactBinary] = None,
        execution_timestamp: Optional[Any] = None,
        source_path: str = "",
        ai_summary: str = "",
    ) -> StepExecution:
        return StepExecution(
            summary=StepSummary(
                step_index=global_index,
                step_name=f"{device_label} / {step_name}",
                intent=f"[{device_label}] {intent}".strip(),
                status=status,
                duration_sec=duration_sec,
                attempts=attempts,
                max_retries=max_retries,
                url="",
            ),
            screenshot=screenshot,
            execution_timestamp=execution_timestamp,
            source_path=source_path,
            ai_summary=ai_summary,
        )


class CurrentArtifactParser(BaseArtifactParser):
    format_name = "current"

    @classmethod
    def matches(cls, catalog: ArchiveCatalog) -> bool:
        return (
            catalog.find_exact("success/summary.json", "failures/summary.json") is not None
            or any(entry.filename.lower() == "step_summary.json" for entry in catalog.entries.values())
        )

    def parse(self) -> ReportData:
        testcase_name = self.upload_file.filename.replace(".zip", "") if self.upload_file.filename else "Unknown Testcase"
        started_at = self._read_optional_text("started_at.txt")
        finished_at = self._read_optional_text("finished_at.txt")

        script_text, script_name = self._extract_required_script()

        top_level_summary = self.catalog.find_exact("success/summary.json", "failures/summary.json")
        summary_payload = None
        if top_level_summary is not None:
            summary_payload = self.catalog.read_json(top_level_summary, max_bytes=settings.MAX_SCRIPT_SIZE_BYTES)
            testcase_name = str(summary_payload.get("test_case_id") or summary_payload.get("testcase_name") or testcase_name)

        # Fallback regex parsing of script source for testcase_name
        if testcase_name in ("execution_artifacts", "Unknown Testcase", ""):
            match = re.search(r"#\s*Test\s*Case\s*ID\s*:\s*([^\r\n]+)", script_text, re.IGNORECASE)
            if match:
                testcase_name = match.group(1).strip()
            else:
                var_match = re.search(r"test_case_id\s*=\s*['\"]([^'\"]+)['\"]", script_text)
                if var_match:
                    testcase_name = var_match.group(1).strip()

        steps: list[StepExecution] = []
        if summary_payload is not None and "steps" in summary_payload:
            for step_metric in summary_payload["steps"]:
                step_index = step_metric["step_index"]
                step_name = step_metric["step_name"]
                status = step_metric["status"]

                if status == "passed":
                    step_dir = self.catalog.parent_dirs_for_predicate(
                        lambda entry: entry.filename.lower() == "step_summary.json" and step_name.lower() in entry.parent.lower()
                    )
                    if step_dir:
                        dir_path = step_dir[0]
                        summary_entry = self.catalog.find_exact(f"{dir_path}/step_summary.json")
                        summary_data = self.catalog.read_json(summary_entry, max_bytes=settings.MAX_SCRIPT_SIZE_BYTES)
                        steps.append(
                            self._build_step(
                                step_dir=dir_path,
                                summary_data=summary_data,
                                fallback_index=step_index,
                                source_path=summary_entry.path,
                            )
                        )
                    else:
                        steps.append(
                            StepExecution(
                                summary=StepSummary(
                                    step_index=step_index,
                                    step_name=step_name,
                                    intent=step_name,
                                    status="passed",
                                    duration_sec=float(step_metric.get("duration_total_sec") or 0.0),
                                    attempts=int(step_metric.get("attempts") or 1),
                                    max_retries=int(step_metric.get("max_retries") or 1),
                                )
                            )
                        )
                else:
                    # Failed step!
                    # Locate latest attempt subdirectory. Appium matrix runs may
                    # nest attempts under failures/<device_slug>/<step_name>.
                    latest_attempt = 1
                    attempt_prefix = f"failures/{step_name}/attempt_{latest_attempt}"
                    for entry in self.catalog.entries.values():
                        if "failures" in entry.path.lower() and step_name.lower() in entry.path.lower():
                            match = re.search(r"attempt_(\d+)", entry.path.lower())
                            if match:
                                attempt = int(match.group(1))
                                if attempt >= latest_attempt:
                                    latest_attempt = attempt
                                    normalized = entry.normalized_path
                                    marker = f"attempt_{attempt}"
                                    attempt_prefix = normalized[: normalized.lower().index(marker) + len(marker)]

                    intent = ""
                    intent_entry = self.catalog.find_exact(f"{attempt_prefix}/intent.txt")
                    if intent_entry:
                        intent = self.catalog.read_text(intent_entry, max_bytes=10 * 1024 * 1024).strip()

                    error_msg = ""
                    error_entry = self.catalog.find_exact(f"{attempt_prefix}/error.txt")
                    if error_entry:
                        error_msg = self.catalog.read_text(error_entry, max_bytes=10 * 1024 * 1024).strip()
                        if len(error_msg) > 10000:
                            error_msg = error_msg[:10000] + "\n... [truncated]"

                    screenshot = None
                    screenshot_entry = self.catalog.find_exact(f"{attempt_prefix}/screenshot.png")
                    if screenshot_entry:
                        screenshot_data = self.catalog.read_bytes(screenshot_entry, max_bytes=settings.MAX_SCREENSHOT_SIZE_BYTES)
                        media_type = self._detect_media_type(screenshot_entry.filename, default="image/png")
                        screenshot = ArtifactBinary(
                            filename=screenshot_entry.filename,
                            media_type=media_type,
                            data=screenshot_data,
                            size_bytes=len(screenshot_data),
                        )

                    steps.append(
                        StepExecution(
                            summary=StepSummary(
                                step_index=step_index,
                                step_name=step_name,
                                intent=intent or step_name,
                                status="failed",
                                duration_sec=float(step_metric.get("duration_total_sec") or 0.0),
                                attempts=int(step_metric.get("attempts") or latest_attempt),
                                max_retries=int(step_metric.get("max_retries") or 1),
                                url="",
                            ),
                            screenshot=screenshot,
                            ai_summary=error_msg or "Step failed execution.",
                            execution_timestamp=None,
                            source_path=f"{attempt_prefix}/step_code.py",
                        )
                    )
        else:
            step_dirs = self.catalog.parent_dirs_for("step_summary.json")
            for fallback_index, step_dir in enumerate(step_dirs):
                summary_entry = self.catalog.find_exact(f"{step_dir}/step_summary.json")
                assert summary_entry is not None
                summary_data = self.catalog.read_json(summary_entry, max_bytes=settings.MAX_SCRIPT_SIZE_BYTES)
                steps.append(
                    self._build_step(
                        step_dir=step_dir,
                        summary_data=summary_data,
                        fallback_index=fallback_index,
                        source_path=summary_entry.path,
                    )
                )

        video = self._extract_optional_video()
        repair_report = self._extract_optional_repair_report()

        final_failure_explanation = None
        explanation_entry = self.catalog.find_exact("final_failure_explanation.json")
        if explanation_entry is not None:
            final_failure_explanation = self.catalog.read_json(explanation_entry, max_bytes=settings.MAX_SCRIPT_SIZE_BYTES)

        return ReportData(
            metadata=ReportMetadata(
                testcase_name=testcase_name,
                started_at=started_at,
                finished_at=finished_at,
                source_format=self.format_name,
            ),
            steps=self._validate_step_collection(steps),
            artifacts=Artifacts(
                execution_video=video,
                final_script=script_text,
                final_script_filename=script_name,
                repair_report=repair_report,
            ),
            final_failure_explanation=final_failure_explanation,
        )

    def _read_optional_text(self, path: str) -> Optional[str]:
        entry = self.catalog.find_exact(path)
        if entry is None:
            return None
        return self.catalog.read_text(entry, max_bytes=2 * 1024 * 1024).strip() or None


class LegacyArtifactParser(BaseArtifactParser):
    format_name = "legacy"

    @classmethod
    def matches(cls, catalog: ArchiveCatalog) -> bool:
        return (
            catalog.find_exact("report.json") is not None
            or any(entry.normalized_path.startswith("steps/") and entry.filename.lower() == "summary.json" for entry in catalog.entries.values())
        )

    def parse(self) -> ReportData:
        report_entry = self.catalog.find_exact("report.json")
        report_payload = self.catalog.read_json(report_entry, max_bytes=settings.MAX_SCRIPT_SIZE_BYTES) if report_entry else {}

        testcase_name = str(report_payload.get("name") or self.upload_file.filename.replace(".zip", ""))
        started_at = report_payload.get("started_at")
        finished_at = report_payload.get("finished_at")

        steps: list[StepExecution] = []
        step_dirs = self.catalog.parent_dirs_for("summary.json")
        step_dirs = [step_dir for step_dir in step_dirs if step_dir.lower().startswith("steps/")]

        for fallback_index, step_dir in enumerate(step_dirs):
            summary_entry = self.catalog.find_exact(f"{step_dir}/summary.json")
            assert summary_entry is not None
            summary_data = self.catalog.read_json(summary_entry, max_bytes=settings.MAX_SCRIPT_SIZE_BYTES)
            steps.append(
                self._build_step(
                    step_dir=step_dir,
                    summary_data=summary_data,
                    fallback_index=fallback_index,
                    source_path=summary_entry.path,
                )
            )

        script_text, script_name = self._extract_required_script()
        video = self._extract_optional_video()
        repair_report = self._extract_optional_repair_report()

        # Fallback regex parsing of script source for testcase_name
        if testcase_name in ("execution_artifacts", "Unknown Testcase", ""):
            match = re.search(r"#\s*Test\s*Case\s*ID\s*:\s*([^\r\n]+)", script_text, re.IGNORECASE)
            if match:
                testcase_name = match.group(1).strip()
            else:
                var_match = re.search(r"test_case_id\s*=\s*['\"]([^'\"]+)['\"]", script_text)
                if var_match:
                    testcase_name = var_match.group(1).strip()

        final_failure_explanation = None
        explanation_entry = self.catalog.find_exact("final_failure_explanation.json")
        if explanation_entry is not None:
            final_failure_explanation = self.catalog.read_json(explanation_entry, max_bytes=settings.MAX_SCRIPT_SIZE_BYTES)

        return ReportData(
            metadata=ReportMetadata(
                testcase_name=testcase_name,
                started_at=str(started_at) if started_at else None,
                finished_at=str(finished_at) if finished_at else None,
                source_format=self.format_name,
            ),
            steps=self._validate_step_collection(steps),
            artifacts=Artifacts(
                execution_video=video,
                final_script=script_text,
                final_script_filename=script_name,
                repair_report=repair_report,
            ),
            final_failure_explanation=final_failure_explanation,
        )


class ZipService:
    """Validated ZIP artifact extraction service with multi-format support."""

    parsers = (MatrixBundleArtifactParser, CurrentArtifactParser, LegacyArtifactParser)

    def extract_and_parse(self, upload_file: UploadFile) -> ReportData:
        try:
            upload_file.file.seek(0)
            with zipfile.ZipFile(upload_file.file) as zip_ref:
                catalog = ArchiveCatalog(zip_ref)

                for parser_cls in self.parsers:
                    if parser_cls.matches(catalog):
                        logger.info("Detected archive format", extra={"format": parser_cls.format_name})
                        return parser_cls(catalog, upload_file).parse()

                raise APIException(
                    error_code=ErrorCode.INVALID_ZIP,
                    message="ZIP structure is not recognized",
                    status_code=400,
                    category=ErrorCategory.VALIDATION,
                    severity=ErrorSeverity.ERROR,
                )

        except zipfile.BadZipFile as exc:
            raise APIException(
                error_code=ErrorCode.INVALID_ZIP,
                message="File is not a valid zip archive",
                status_code=400,
                category=ErrorCategory.VALIDATION,
                severity=ErrorSeverity.ERROR,
                details={"error": str(exc)},
            ) from exc
        except APIException:
            raise
        except Exception as exc:
            raise APIException(
                error_code=ErrorCode.ZIP_EXTRACTION_FAILED,
                message="Failed to extract and parse ZIP contents",
                status_code=500,
                category=ErrorCategory.INTERNAL,
                severity=ErrorSeverity.ERROR,
                details={"error": str(exc)},
            ) from exc
