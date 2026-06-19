import io
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable, List, Sequence

from fastapi import HTTPException

from app.core.config import Settings
from app.core.logging import logger
from app.core.utils import safe_decode
from app.services.chunker import Chunk, build_chunks
from app.services.csv_writer import write_methods_to_csv
from app.services.scanner import MethodInfo, parse_source, prepare_methods_with_inits
from app.services.validator import ValidationError, validate_chunk_order, validate_methods


IGNORED_DIRS = {
    ".venv",
    "venv",
    ".git",
    "node_modules",
    "__pycache__",
}


@dataclass
class ExtractionResult:
    methods: List[MethodInfo]
    chunks: List[Chunk]
    csv_bytes: bytes


@dataclass
class ProjectExtractionResult:
    methods: List[MethodInfo]
    chunks: List[Chunk]
    csv_bytes: bytes
    python_file_count: int
    total_file_count: int
    skipped_file_count: int


def extract_methods_from_source(
    source_text: str,
    *,
    max_chars_per_chunk: int,
    ignore_method_names: Sequence[str] | None = None,
    include_method_name_pattern: str | None = None,
) -> ExtractionResult:
    methods, init_map, global_blocks = parse_source(
        source_text,
        ignore_method_names=ignore_method_names,
        include_method_name_pattern=include_method_name_pattern,
    )
    prepared_methods = prepare_methods_with_inits(
        methods,
        init_map,
        global_blocks,
    )
    validate_methods(prepared_methods)
    validate_chunk_order(prepared_methods)
    chunks = build_chunks(
        prepared_methods,
        max_chars_per_chunk=max_chars_per_chunk,
    )
    csv_bytes = write_methods_to_csv(prepared_methods)
    return ExtractionResult(methods=prepared_methods, chunks=chunks, csv_bytes=csv_bytes)


def _validate_zip_payload(zip_bytes: bytes, settings: Settings) -> None:
    if settings.MAX_ZIP_SIZE_MB > 0:
        max_zip_bytes = settings.MAX_ZIP_SIZE_MB * 1024 * 1024
        if len(zip_bytes) > max_zip_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"ZIP file exceeds maximum allowed size ({settings.MAX_ZIP_SIZE_MB} MB).",
            )


def _is_ignored_path(path: PurePosixPath) -> bool:
    ignored = {item.lower() for item in IGNORED_DIRS}
    return any(part.lower() in ignored for part in path.parts[:-1])


def _iter_safe_file_entries(archive: zipfile.ZipFile) -> Iterable[zipfile.ZipInfo]:
    for info in archive.infolist():
        if info.is_dir():
            continue

        path = PurePosixPath(info.filename)
        if path.is_absolute() or ".." in path.parts:
            raise HTTPException(
                status_code=400,
                detail=f"ZIP contains an unsafe path: {info.filename}",
            )

        yield info


def extract_methods_from_project_zip(
    zip_bytes: bytes,
    *,
    settings: Settings,
    ignore_method_names: Sequence[str] | None = None,
    include_method_name_pattern: str | None = None,
) -> ProjectExtractionResult:
    _validate_zip_payload(zip_bytes, settings)

    all_methods: List[MethodInfo] = []
    python_file_count = 0
    total_file_count = 0
    skipped_file_count = 0
    extracted_size_bytes = 0

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as archive:
            for info in _iter_safe_file_entries(archive):
                total_file_count += 1

                if settings.MAX_FILE_COUNT > 0 and total_file_count > settings.MAX_FILE_COUNT:
                    raise HTTPException(
                        status_code=400,
                        detail="Project contains too many files.",
                    )

                extracted_size_bytes += info.file_size
                if settings.MAX_EXTRACTED_SIZE_MB > 0:
                    max_bytes = settings.MAX_EXTRACTED_SIZE_MB * 1024 * 1024
                    if extracted_size_bytes > max_bytes:
                        raise HTTPException(
                            status_code=400,
                            detail="Extracted project size exceeds allowed limit.",
                        )

                path = PurePosixPath(info.filename)
                if _is_ignored_path(path) or path.suffix.lower() != ".py":
                    continue

                python_file_count += 1
                if settings.MAX_PY_FILES > 0 and python_file_count > settings.MAX_PY_FILES:
                    raise HTTPException(
                        status_code=400,
                        detail="Too many Python files in project.",
                    )

                try:
                    with archive.open(info, "r") as file_handle:
                        source_text = safe_decode(file_handle.read())

                    result = extract_methods_from_source(
                        source_text,
                        max_chars_per_chunk=settings.MAX_CHARS_PER_CHUNK,
                        ignore_method_names=ignore_method_names,
                        include_method_name_pattern=include_method_name_pattern,
                    )
                    all_methods.extend(result.methods)
                except (SyntaxError, ValidationError) as exc:
                    skipped_file_count += 1
                    logger.warning(f"Skipping invalid Python file {info.filename}: {exc}")
                except Exception as exc:
                    skipped_file_count += 1
                    logger.error(f"Failed processing file {info.filename}: {exc}")
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid ZIP archive.") from exc

    if not all_methods:
        raise HTTPException(
            status_code=400,
            detail="No extractable Python methods found in project.",
        )

    validate_chunk_order(all_methods)
    chunks = build_chunks(
        all_methods,
        max_chars_per_chunk=settings.MAX_CHARS_PER_CHUNK,
    )
    csv_bytes = write_methods_to_csv(all_methods)
    return ProjectExtractionResult(
        methods=all_methods,
        chunks=chunks,
        csv_bytes=csv_bytes,
        python_file_count=python_file_count,
        total_file_count=total_file_count,
        skipped_file_count=skipped_file_count,
    )
