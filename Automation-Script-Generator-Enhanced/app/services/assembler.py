# app/services/assembler.py
"""
Script Assembler

Assembles generated automation test script code into executable script files.
"""

from pathlib import Path
import tempfile
import re
from datetime import datetime, timezone
from typing import Optional
import logging
import aiofiles
import zipfile
import io

from app.core.config import get_settings
from app.utils.sanitization import sanitize_test_case_id

logger = logging.getLogger("assembler")
settings = get_settings()


class ScriptAssemblerError(Exception):
    """Raised when script assembly fails."""
    pass


class ScriptAssembler:
    """
    Assembles generated code into a .py file.
    
    Features:
    - Safe filesystem writes with atomic operations
    - Collision avoidance via hashed filenames
    - Final formatting and provenance headers
    - Async file I/O support
    """
    
    def __init__(self, output_dir: str | Path | None = None):
        if output_dir is not None:
            self.output_dir = Path(output_dir).resolve()
        else:
            project_root = Path(__file__).resolve().parents[2]
            self.output_dir = project_root / "outputs" / "generated_scripts"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.max_file_size = settings.MAX_SCRIPT_SIZE_BYTES
    
    def assemble(
        self,
        test_case_id: str,
        code: str,
        framework: str = "playwright",
        run_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> Path:
        """
        Write the generated code into a script file (synchronous version).

        Args:
            test_case_id: Test case identifier
            code: Generated code
            framework: Target framework (playwright/selenium/appium/cypress)
            run_id: Optional run identifier for unique filenames

        Returns:
            Path to the generated file

        Raises:
            ScriptAssemblerError: If assembly fails
        """
        if not isinstance(code, str) or not code.strip():
            raise ScriptAssemblerError(
                "Generated code is empty or invalid; cannot assemble script."
            )

        safe_test_case_id = sanitize_test_case_id(test_case_id)
        ext = ".js" if framework.lower() == "cypress" else ".py"
        if run_id:
            file_name = f"test_{safe_test_case_id}_{run_id}{ext}"
        else:
            file_name = f"test_{safe_test_case_id}{ext}"
        file_path = self.output_dir / file_name
        
        formatted_code = self._format_code(code)
        final_code = self._with_header(test_case_id, formatted_code, request_id=request_id)

        if len(final_code.encode("utf-8")) > self.max_file_size:
            raise ScriptAssemblerError(
                f"Generated script exceeds size limit ({self.max_file_size} bytes)"
            )

        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)

            # Atomic write via temp file
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.output_dir,
                delete=False,
            ) as tmp:
                tmp.write(final_code)
                tmp_path = Path(tmp.name)
            
            # Permission hardening (Unix-safe)
            try:
                tmp_path.chmod(0o600)
            except OSError:
                pass
            
            tmp_path.replace(file_path)
            
            logger.info("Script assembled | path=%s | size=%d", file_path, len(final_code))
            return file_path
            
        except Exception as exc:
            raise ScriptAssemblerError(
                f"Failed to assemble script for test_case_id='{test_case_id}'"
            ) from exc
    
    async def assemble_async(
        self,
        test_case_id: str,
        code: str,
        framework: str = "playwright",
        run_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> Path:
        """
        Write the generated code into a script file (async version).

        Uses aiofiles for non-blocking file I/O.
        """
        if not isinstance(code, str) or not code.strip():
            raise ScriptAssemblerError(
                "Generated code is empty or invalid; cannot assemble script."
            )

        safe_test_case_id = sanitize_test_case_id(test_case_id)
        ext = ".js" if framework.lower() == "cypress" else ".py"
        if run_id:
            file_name = f"test_{safe_test_case_id}_{run_id}{ext}"
        else:
            file_name = f"test_{safe_test_case_id}{ext}"
        file_path = self.output_dir / file_name
        
        formatted_code = self._format_code(code)
        final_code = self._with_header(test_case_id, formatted_code, request_id=request_id)

        if len(final_code.encode("utf-8")) > self.max_file_size:
            raise ScriptAssemblerError(
                f"Generated script exceeds size limit ({self.max_file_size} bytes)"
            )

        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)

            import uuid
            tmp_path = self.output_dir / f".tmp_{safe_test_case_id}_{uuid.uuid4().hex}{ext}"

            async with aiofiles.open(tmp_path, mode="w", encoding="utf-8") as f:
                await f.write(final_code)
            
            # Atomic rename
            tmp_path.replace(file_path)
            
            logger.info("Script assembled (async) | path=%s | size=%d", file_path, len(final_code))
            return file_path
            
        except Exception as exc:
            raise ScriptAssemblerError(
                f"Failed to assemble script for test_case_id='{test_case_id}'"
            ) from exc

    async def assemble_zip_async(
        self,
        test_case_id: str,
        files: dict[str, str],
    ) -> Path:
        """
        Write multiple generated codes into a .zip file (async version).
        
        Args:
            test_case_id: Test case identifier
            files: Dictionary mapping filename to generated code
            
        Returns:
            Path to the generated zip file
            
        Raises:
            ScriptAssemblerError: If assembly fails
        """
        if not files:
            raise ScriptAssemblerError("No files provided for zip assembly.")
        
        safe_test_case_id = sanitize_test_case_id(test_case_id)
        zip_path = self.output_dir / f"test_{safe_test_case_id}.zip"
        
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            
            import uuid
            tmp_path = self.output_dir / f".tmp_{safe_test_case_id}_{uuid.uuid4().hex}.zip"
            
            def write_zip():
                with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for filename, code in files.items():
                        if not code or not code.strip():
                            continue
                        formatted_code = self._format_code(code)
                        final_code = self._with_header(test_case_id, formatted_code)
                        zf.writestr(filename, final_code.encode("utf-8"))
            
            import asyncio
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, write_zip)
            
            # Atomic rename
            tmp_path.replace(zip_path)
            
            logger.info("Script zip assembled (async) | path=%s | size=%d files", zip_path, len(files))
            return zip_path
            
        except Exception as exc:
            raise ScriptAssemblerError(
                f"Failed to assemble zip for test_case_id='{test_case_id}'"
            ) from exc
    
    _CODE_FENCE = re.compile(r"^\s*(`{3,}|~{3,})\w*\s*$")

    def _format_code(self, code: str) -> str:
        """Final formatting pass."""
        lines = code.splitlines()

        # Remove leading empty lines
        while lines and not lines[0].strip():
            lines.pop(0)

        # Strip trailing whitespace and markdown code fences
        cleaned = []
        for line in lines:
            if self._CODE_FENCE.match(line):
                continue
            cleaned.append(line.rstrip())

        return "\n".join(cleaned).rstrip() + "\n"
    
    def _with_header(
        self,
        test_case_id: str,
        code: str,
        request_id: Optional[str] = None,
    ) -> str:
        """Prepend provenance header."""
        header = [
            "# -*- coding: utf-8 -*-",
            "# ------------------------------------------------------------",
            "# AUTO-GENERATED FILE - DO NOT EDIT MANUALLY",
            f"# Test Case ID : {test_case_id}",
            f"# Generated At : {datetime.now(timezone.utc).replace(microsecond=0).isoformat()} UTC",
            f"# Generator    : {settings.APP_NAME} v{settings.VERSION}",
        ]
        if request_id:
            header.append(f"# Request ID   : {request_id}")
        header += [
            "# ------------------------------------------------------------",
            "",
        ]
        return "\n".join(header) + code

