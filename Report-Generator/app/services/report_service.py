import base64
import os
from datetime import datetime, timezone
from urllib.parse import urlsplit

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.core.logger import get_logger
from app.models.domain import ArtifactBinary, ReportData, StepExecution
from app.models.view import ReportArtifactsView, ReportStepView, ReportViewModel


logger = get_logger(__name__)


class ReportService:
    """Render self-contained HTML reports from normalized view models."""

    def __init__(self):
        templates_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
        self.jinja_env = Environment(
            loader=FileSystemLoader(templates_dir),
            autoescape=select_autoescape(enabled_extensions=("html", "xml")),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def generate_html(self, report_data: ReportData) -> str:
        try:
            view_model = self._build_view_model(report_data)
            template = self.jinja_env.get_template("report.html")
            return template.render(report=view_model.model_dump())
        except Exception as exc:
            logger.error("Failed to generate HTML", extra={"error": str(exc)})
            raise

    def _build_view_model(self, report_data: ReportData) -> ReportViewModel:
        steps = sorted(report_data.steps, key=lambda item: item.summary.step_index)

        passed_count = sum(1 for step in steps if step.summary.status == "passed")
        total_steps = len(steps)
        failed_count = total_steps - passed_count
        total_duration = round(sum(step.summary.duration_sec for step in steps), 2)
        success_rate = round((passed_count / total_steps) * 100, 2) if total_steps else 0.0

        return ReportViewModel(
            testcase_name=report_data.metadata.testcase_name,
            generated_at=self._iso_now(),
            started_at=report_data.metadata.started_at or "N/A",
            finished_at=report_data.metadata.finished_at or "N/A",
            overall_description=report_data.metadata.overall_description,
            total_steps=total_steps,
            passed_steps=passed_count,
            failed_steps=failed_count,
            total_duration=total_duration,
            success_rate=success_rate,
            source_format=report_data.metadata.source_format,
            steps=[self._build_step_view(step, display_index=index) for index, step in enumerate(steps, start=1)],
            artifacts=self._build_artifacts_view(report_data),
            final_failure_explanation=report_data.final_failure_explanation,
        )

    def _build_step_view(self, step: StepExecution, *, display_index: int) -> ReportStepView:
        screenshot_data = ""
        screenshot_media_type = ""

        if step.screenshot is not None:
            screenshot_data = self._to_base64(step.screenshot)
            screenshot_media_type = step.screenshot.media_type

        return ReportStepView(
            step_id=f"step-{display_index}",
            index=display_index,
            name=step.summary.step_name or f"Step {step.summary.step_index}",
            status=step.summary.status,
            intent=step.summary.intent,
            duration=round(step.summary.duration_sec, 2),
            attempts=step.summary.attempts,
            max_retries=step.summary.max_retries,
            url=self._sanitize_url(step.summary.url),
            ai_summary=step.ai_summary or "AI enrichment unavailable for this step.",
            screenshot_data=screenshot_data,
            screenshot_media_type=screenshot_media_type,
            timestamp=self._normalize_timestamp(step.execution_timestamp),
        )

    def _build_artifacts_view(self, report_data: ReportData) -> ReportArtifactsView:
        execution_video_data = ""
        execution_video_media_type = ""

        if report_data.artifacts.execution_video is not None:
            execution_video_data = self._to_base64(report_data.artifacts.execution_video)
            execution_video_media_type = report_data.artifacts.execution_video.media_type

        repair_report = None
        if report_data.artifacts.repair_report:
            import copy
            repair_report = copy.deepcopy(report_data.artifacts.repair_report)
            for r in repair_report.get("repairs", []):
                step_id = r.get("step_id", "")
                if step_id and "__" in step_id:
                    parts = step_id.split("__")
                    try:
                        step_num = int(parts[0])
                        r["display_step_name"] = f"STEP {step_num}"
                    except ValueError:
                        r["display_step_name"] = step_id
                else:
                    r["display_step_name"] = step_id

        final_script = report_data.artifacts.final_script or ""
        normalized_script = self._normalize_script_spacing(final_script)

        return ReportArtifactsView(
            execution_video_data=execution_video_data,
            execution_video_media_type=execution_video_media_type,
            final_script=normalized_script,
            final_script_filename=report_data.artifacts.final_script_filename or "final_script.py",
            repair_report=repair_report,
        )

    def _normalize_script_spacing(self, script: str) -> str:
        if not script:
            return ""

        # Normalize carriage returns to Unix newlines
        normalized = script.replace("\r\n", "\n").replace("\r", "\n")
        lines = normalized.split("\n")

        if len(lines) < 4:
            return normalized

        # Calculate double-spacing ratio
        non_empty_count = 0
        non_empty_followed_by_empty_count = 0
        for i in range(len(lines) - 1):
            if lines[i].strip():
                non_empty_count += 1
                if not lines[i + 1].strip():
                    non_empty_followed_by_empty_count += 1

        is_double_spaced = (
            non_empty_count > 2
            and (non_empty_followed_by_empty_count / non_empty_count) >= 0.9
        )

        if is_double_spaced:
            collapsed_lines = []
            blank_counter = 0
            for line in lines:
                if not line.strip():
                    blank_counter += 1
                    # Skip the 1st, 3rd, 5th... blank lines in a row
                    if blank_counter % 2 != 0:
                        continue
                    collapsed_lines.append(line)
                else:
                    blank_counter = 0
                    collapsed_lines.append(line)
            result = "\n".join(collapsed_lines)
            if script.endswith("\n") and not result.endswith("\n"):
                result += "\n"
            return result

        return normalized

    def _to_base64(self, artifact: ArtifactBinary) -> str:
        return base64.b64encode(artifact.data).decode("utf-8")

    def _sanitize_url(self, value: str) -> str:
        if not value:
            return ""
        parsed = urlsplit(value.strip())
        if parsed.scheme.lower() in {"http", "https"}:
            return value.strip()
        return ""

    def _normalize_timestamp(self, value) -> str:
        if value is None or value == "":
            return "N/A"

        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
            except Exception:
                return str(value)

        return str(value)

    def _iso_now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
