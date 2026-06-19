import asyncio
import logging
from copy import deepcopy
from typing import Optional, Callable

from app.models.step_repair import StepRepairRequest
from app.core.config import get_settings
from app.core.metrics import get_metrics
from app.core.exceptions import StepNotRepairableError

logger = logging.getLogger("service.repair")


class RepairService:
    """
    Production-grade repair service.

    Responsibilities:
    - Bounded concurrency
    - Timeout enforcement
    - Thread-safe execution
    - Metrics integration
    - No HTTP coupling
    """

    def __init__(
        self,
        pipeline_fn: Callable[..., tuple[str, str]],
        semaphore: asyncio.Semaphore,
    ):
        self.settings = get_settings()
        self.metrics = get_metrics()
        self.pipeline_fn = pipeline_fn
        self.semaphore = semaphore
        self.timeout_seconds = self.settings.LLM_TIMEOUT_SECONDS + 30

    async def repair_step(
        self,
        *,
        request: StepRepairRequest,
        error_image_bytes: Optional[bytes],
        request_id: str,
    ) -> tuple[str, str]:
        """
        Executes repair pipeline with bounded concurrency and timeout.

        Returns:
            (repaired_code, action_type)

        Raises:
            asyncio.TimeoutError
            StepNotRepairableError
            Exception
        """

        async with self.semaphore:
            logger.debug(
                "REPAIR_SERVICE_START | request_id=%s | step_id=%s",
                request_id,
                request.step_id,
            )
            start = asyncio.get_running_loop().time()
            outcome = "error"

            try:
                result = await asyncio.wait_for(
                    self.pipeline_fn(
                        request=deepcopy(request),
                        error_image_bytes=error_image_bytes,
                        request_id=request_id,
                    ),
                    timeout=self.timeout_seconds,
                )
                outcome = "success"

                logger.debug(
                    "REPAIR_SERVICE_SUCCESS | request_id=%s | step_id=%s",
                    request_id,
                    request.step_id,
                )

                return result

            except asyncio.TimeoutError:
                outcome = "timeout"
                logger.error(
                    "REPAIR_SERVICE_TIMEOUT | request_id=%s | step_id=%s | timeout=%s",
                    request_id,
                    request.step_id,
                    self.timeout_seconds,
                )
                raise

            except StepNotRepairableError:
                outcome = "not_repairable"
                logger.info(
                    "REPAIR_SERVICE_NOT_REPAIRABLE | request_id=%s | step_id=%s",
                    request_id,
                    request.step_id,
                )
                raise

            except Exception as exc:
                logger.exception(
                    "REPAIR_SERVICE_FAILURE | request_id=%s | step_id=%s",
                    request_id,
                    request.step_id,
                )
                raise
            finally:
                self.metrics.repair_duration_seconds.observe(
                    asyncio.get_running_loop().time() - start,
                    outcome=outcome,
                )
