import asyncio
from fastapi import UploadFile
from time import perf_counter

from app.core.config import get_settings
from app.core.logger import get_logger
from app.services.ai import AIService
from app.services.zip_service import ZipService
from app.services.report_service import ReportService
from app.models.domain import ReportData

logger = get_logger(__name__)
settings = get_settings()

class ReportWorkflow:
    """Orchestrates the business logic of generating a report."""
    
    def __init__(self, ai_service: AIService, zip_service: ZipService, report_service: ReportService):
        self.ai_service = ai_service
        self.zip_service = zip_service
        self.report_service = report_service
        
    async def execute(self, file: UploadFile) -> str:
        """Execute the end-to-end report generation workflow."""
        zip_start = perf_counter()
        
        # 1. Extract and Parse ZIP Data (Runs in thread to avoid blocking event loop)
        report_data: ReportData = await asyncio.to_thread(self.zip_service.extract_and_parse, file)
        
        zip_duration = perf_counter() - zip_start
        logger.info(
            "ZIP extraction completed",
            extra={
                "duration_sec": round(zip_duration, 2),
                "steps": len(report_data.steps),
                "source_format": report_data.metadata.source_format,
                "video_present": report_data.artifacts.execution_video is not None,
            },
        )

        # 2. AI Enrichment (Async gathering)
        passed_steps = sum(1 for s in report_data.steps if s.summary.status == "passed")
        total_steps = len(report_data.steps)
        failed_steps = total_steps - passed_steps
        total_duration = sum(s.summary.duration_sec for s in report_data.steps)
        
        ai_start = perf_counter()
        ai_status = "completed"
        try:
            # We run both the step enrichment and the overall narrative concurrently
            _, overall_description = await asyncio.wait_for(
                asyncio.gather(
                    self.ai_service.enrich_steps_with_summaries(report_data.steps),
                    self.ai_service.generate_overall_description(
                        total_steps=total_steps,
                        passed_steps=passed_steps,
                        failed_steps=failed_steps,
                        duration_sec=total_duration,
                    ),
                ),
                timeout=settings.AI_OVERALL_TIMEOUT_SECONDS,
            )
            if overall_description:
                report_data.metadata.overall_description = overall_description
            
        except asyncio.TimeoutError:
            ai_status = "timed_out"
            logger.warning("AI enrichment timed out — generating report without AI summaries")
        except Exception as e:
            ai_status = "fallback_without_ai"
            logger.warning(
                "AI enrichment failed — generating report without AI summaries",
                extra={"error": str(e)},
            )
            
        ai_duration = perf_counter() - ai_start
        logger.info(
            "AI enrichment phase finished",
            extra={
                "duration_sec": round(ai_duration, 2),
                "steps": total_steps,
                "status": ai_status,
            },
        )

        # 3. HTML Generation (Runs in thread because Jinja2 is CPU bound)
        render_start = perf_counter()
        html_content = await asyncio.to_thread(self.report_service.generate_html, report_data)
        
        render_duration = perf_counter() - render_start
        logger.info(
            "HTML rendering completed",
            extra={
                "duration_sec": round(render_duration, 2),
                "html_size_bytes": len(html_content.encode("utf-8")),
            },
        )

        return html_content
