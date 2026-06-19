# tests/test_assembler.py
"""
Tests for ScriptAssembler (app/services/assembler.py)

Covers:
- output_dir parameter is now correctly honoured (P3-T2 regression)
- Default output_dir resolves to outputs/generated_scripts/
- assemble() writes file with expected header
- assemble() raises on empty code
- assemble() raises when code exceeds MAX_SCRIPT_SIZE_BYTES
- assemble_async() writes file correctly
- Path traversal: sanitize_test_case_id prevents directory escape
- Overwrite collision: second assemble() replaces the first
"""

import asyncio
import pytest
from pathlib import Path
import tempfile

from app.services.assembler import ScriptAssembler, ScriptAssemblerError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_CODE = "print('hello world')\n"


@pytest.fixture
def tmp_assembler(tmp_path):
    """Assembler that writes to a pytest-managed temp dir."""
    return ScriptAssembler(output_dir=str(tmp_path))


# ---------------------------------------------------------------------------
# Tests — output_dir parameter
# ---------------------------------------------------------------------------

class TestOutputDir:

    def test_custom_output_dir_honoured(self, tmp_path):
        a = ScriptAssembler(output_dir=str(tmp_path))
        assert a.output_dir == tmp_path.resolve()

    def test_default_output_dir_is_outputs_generated_scripts(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "a" * 32)
        a = ScriptAssembler()
        assert a.output_dir.parts[-2:] == ("outputs", "generated_scripts")

    def test_none_output_dir_uses_default(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "a" * 32)
        a = ScriptAssembler(output_dir=None)
        assert a.output_dir.parts[-2:] == ("outputs", "generated_scripts")


# ---------------------------------------------------------------------------
# Tests — synchronous assemble()
# ---------------------------------------------------------------------------

class TestAssemble:

    def test_writes_python_file(self, tmp_assembler):
        path = tmp_assembler.assemble("TC_001", VALID_CODE)
        assert path.exists()
        assert path.suffix == ".py"

    def test_output_contains_header(self, tmp_assembler):
        path = tmp_assembler.assemble("TC_HEADER", VALID_CODE)
        content = path.read_text(encoding="utf-8")
        assert "AUTO-GENERATED FILE" in content
        assert "TC_HEADER" in content

    def test_output_contains_code(self, tmp_assembler):
        path = tmp_assembler.assemble("TC_CODE", VALID_CODE)
        content = path.read_text(encoding="utf-8")
        assert "print('hello world')" in content

    def test_empty_code_raises(self, tmp_assembler):
        with pytest.raises(ScriptAssemblerError, match="empty"):
            tmp_assembler.assemble("TC_EMPTY", "   ")

    def test_none_code_raises(self, tmp_assembler):
        with pytest.raises(ScriptAssemblerError):
            tmp_assembler.assemble("TC_NONE", None)

    def test_oversize_code_raises(self, tmp_assembler, monkeypatch):
        monkeypatch.setattr(tmp_assembler, "max_file_size", 10)
        with pytest.raises(ScriptAssemblerError, match="size limit"):
            tmp_assembler.assemble("TC_BIG", "x" * 100)

    def test_second_assemble_overwrites_first(self, tmp_assembler):
        tmp_assembler.assemble("TC_OVERWRITE", "print(1)\n")
        path = tmp_assembler.assemble("TC_OVERWRITE", "print(2)\n")
        assert "print(2)" in path.read_text()

    def test_test_case_id_sanitised_in_filename(self, tmp_assembler):
        """Malicious test_case_id must not result in a path outside output_dir."""
        path = tmp_assembler.assemble("../escape_attempt", VALID_CODE)
        # File must remain inside output_dir
        assert str(path).startswith(str(tmp_assembler.output_dir))


# ---------------------------------------------------------------------------
# Tests — async assemble_async()
# ---------------------------------------------------------------------------

class TestAssembleAsync:

    @pytest.mark.asyncio
    async def test_async_writes_file(self, tmp_assembler):
        path = await tmp_assembler.assemble_async("TC_ASYNC", VALID_CODE)
        assert path.exists()
        assert path.suffix == ".py"

    @pytest.mark.asyncio
    async def test_async_output_contains_code(self, tmp_assembler):
        path = await tmp_assembler.assemble_async("TC_ASYNC_CONTENT", VALID_CODE)
        assert "print('hello world')" in path.read_text()

    @pytest.mark.asyncio
    async def test_async_empty_code_raises(self, tmp_assembler):
        with pytest.raises(ScriptAssemblerError):
            await tmp_assembler.assemble_async("TC_ASYNC_EMPTY", "")
