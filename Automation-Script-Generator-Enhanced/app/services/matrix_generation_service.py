import logging
import time
import uuid
from pathlib import Path
from typing import Dict

from app.core.exceptions import CodeGenerationError, ExtractionError
from app.core.metrics import get_metrics
from app.core.token_tracker import (
    get_input_tokens,
    get_output_tokens,
    get_total_tokens,
    reset_tokens,
)
from app.models.test_case import TestCase
from app.services.assembler import ScriptAssembler
from app.services.cir_builder import CIRBuilder
from app.services.generators.playwright_matrix_generator import PlaywrightMatrixGenerator
from app.services.validator import CIRValidationError, CIRValidator
from app.services.generation_service import GeneratedScriptResult


logger = logging.getLogger("services.matrix_generation")


class MatrixGenerationService:
    """Coordinates the CIR-to-script pipeline specifically for multi-device ZIP generation."""

    def __init__(
        self,
        cir_builder: CIRBuilder | None = None,
        validator: CIRValidator | None = None,
        assembler: ScriptAssembler | None = None,
    ):
        self._cir_builder = cir_builder or CIRBuilder()
        self._validator = validator or CIRValidator()
        self._assembler = assembler or ScriptAssembler()
        self._metrics = get_metrics()

    async def generate(self, test_case: TestCase) -> GeneratedScriptResult:
        request_id = uuid.uuid4().hex[:8]
        request_start = time.perf_counter()

        reset_tokens()

        logger.info(
            "Matrix Generation started | id=%s | test_case_id=%s",
            request_id,
            test_case.test_case_id,
        )

        cir_test_case, context_map = await self._build_cir(test_case, request_id)
        self._validate_cir(cir_test_case, request_id)
        generated_code_dict = await self._generate_code(cir_test_case, context_map, request_id)
        path = await self._assemble(test_case.test_case_id, generated_code_dict, request_id)

        duration_ms = (time.perf_counter() - request_start) * 1000
        input_tokens = get_input_tokens()
        output_tokens = get_output_tokens()
        total_tokens = get_total_tokens()

        self._metrics.scripts_generated.increment()
        self._metrics.script_size_bytes.observe(path.stat().st_size)

        logger.info(
            "Matrix Generation success | id=%s | test_case_id=%s | duration_ms=%.2f | tokens=%d",
            request_id,
            test_case.test_case_id,
            duration_ms,
            total_tokens,
        )

        return GeneratedScriptResult(
            request_id=request_id,
            path=path,
            duration_ms=duration_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        )

    async def _build_cir(self, test_case: TestCase, request_id: str):
        t0 = time.perf_counter()
        cir_test_case, context_map = await self._cir_builder.build(test_case)

        logger.info(
            "CIR build complete | id=%s | setup=%d | steps=%d | duration_ms=%.2f",
            request_id,
            len(cir_test_case.setup),
            len(cir_test_case.steps),
            (time.perf_counter() - t0) * 1000,
        )

        return cir_test_case, context_map

    def _validate_cir(self, cir_test_case, request_id: str) -> None:
        t0 = time.perf_counter()

        try:
            self._validator.validate_blocks(cir_test_case.setup + cir_test_case.steps)
        except CIRValidationError as exc:
            logger.warning("CIR validation failed | id=%s | error=%s", request_id, exc)
            self._metrics.record_error("cir_validation")
            raise ExtractionError(message=f"CIR validation failed: {exc}") from exc

        logger.info(
            "CIR validation passed | id=%s | duration_ms=%.2f",
            request_id,
            (time.perf_counter() - t0) * 1000,
        )

    async def _generate_code(self, cir_test_case, context_map, request_id: str) -> Dict[str, str]:
        t0 = time.perf_counter()
        generator = PlaywrightMatrixGenerator()

        generated_code_dict = await generator.generate(
            cir_test_case=cir_test_case,
            context_map=context_map,
        )

        if not generated_code_dict:
            self._metrics.record_error("empty_script")
            raise CodeGenerationError(message="Generator returned empty script dictionary.")

        logger.info(
            "Code generation complete | id=%s | files=%d | duration_ms=%.2f",
            request_id,
            len(generated_code_dict),
            (time.perf_counter() - t0) * 1000,
        )

        return generated_code_dict

    async def _assemble(self, test_case_id: str, code_dict: Dict[str, str], request_id: str) -> Path:
        t0 = time.perf_counter()
        script_path = await self._assembler.assemble_zip_async(
            test_case_id=test_case_id,
            files=code_dict,
        )

        path = Path(script_path)
        if not path.exists():
            logger.error("Assembly failed | id=%s | path=%s", request_id, script_path)
            self._metrics.record_error("assembly")
            raise CodeGenerationError(message="Failed to assemble zip file.")

        logger.info(
            "Assembly complete | id=%s | path=%s | duration_ms=%.2f",
            request_id,
            path,
            (time.perf_counter() - t0) * 1000,
        )

        return path
