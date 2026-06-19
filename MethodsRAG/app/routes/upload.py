"""Upload methods with optimized parallel processing pipeline."""

import asyncio
import io
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.core.analytics import log_api_call
from app.core.cache import cache_clear
from app.core.config import get_settings
from app.core.exceptions import DatabaseError, ValidationError
from app.core.logging import logger
from app.core.metrics import Metrics
from app.core.rate_limiter import rate_limit_dependency
from app.core.security import verify_api_key
from app.core.validation import (
    FileValidationError,
    validate_file_format,
    validate_file_size,
    validate_raw_method,
)
from app.db.mongo import get_methods_collection
from app.services.dedupe_search_helper import search_similar_methods
from app.services.dedupe_summary import generate_method_dedupe_summary
from app.services.dedupe_verifier import llm_verify_method_duplicate
from app.services.embeddings import embed_text
from app.services.code_provenance import (
    STORED_FRAMEWORK_FIELD,
    STORED_LANGUAGE_FIELD,
    normalize_framework,
    normalize_language,
    resolve_code_provenance,
)
from app.services.method_madl import get_method_madl

settings = get_settings()
router = APIRouter()


def _build_method_entries(
    df: pd.DataFrame,
    *,
    default_framework: str | None,
    default_language: str | None,
) -> List[Dict[str, str | None]]:
    seen = set()
    entries: List[Dict[str, str | None]] = []

    def get_row_value(row: pd.Series, *column_names: str) -> str:
        for column_name in column_names:
            if column_name in row.index:
                return str(row.get(column_name, "")).strip()
        return ""

    for _, row in df.iterrows():
        raw_method = str(row.get("Raw Method", "")).strip()
        if len(raw_method) < 10 or raw_method in seen:
            continue

        row_framework = get_row_value(row, "Framework", "framework") or default_framework
        row_language = get_row_value(row, "Language", "language") or default_language
        resolved_framework, resolved_language = resolve_code_provenance(
            raw_method,
            explicit_framework=row_framework,
            explicit_language=row_language,
        )

        seen.add(raw_method)
        entries.append(
            {
                "raw_method": raw_method,
                "framework": resolved_framework,
                "language": resolved_language,
            }
        )

    return entries


async def process_single_method(
    raw_method: str,
    *,
    framework: str | None = None,
    language: str | None = None,
) -> Dict[str, Any] | None:
    """
    Process a single raw method through the entire pipeline.
    Returns the processed document or None if duplicate/invalid.
    """
    try:
        raw_method = validate_raw_method(raw_method)
    except ValidationError:
        logger.debug("Raw method validation failed")
        return None

    try:
        dedupe_summary = await generate_method_dedupe_summary(raw_method)
        matches = await search_similar_methods(query=dedupe_summary, limit=3)
        is_duplicate = await llm_verify_method_duplicate(
            candidate={
                "method_name": "",
                "raw_method_code": raw_method,
            },
            top_matches=matches,
        )

        if is_duplicate:
            logger.debug("Method identified as duplicate, skipping")
            return None

        madl_task = asyncio.create_task(
            get_method_madl(
                raw_method,
                framework=framework,
                language=language,
            )
        )
        summary_embed_task = asyncio.create_task(asyncio.to_thread(embed_text, dedupe_summary))
        raw_embed_task = asyncio.create_task(asyncio.to_thread(embed_text, raw_method))

        madl = await madl_task
        summary_embedding, raw_method_embedding = await asyncio.gather(
            summary_embed_task,
            raw_embed_task,
        )

        madl_str = json.dumps(madl, sort_keys=True)
        madl_embedding, main_vector = await asyncio.gather(
            asyncio.to_thread(embed_text, madl_str),
            asyncio.to_thread(embed_text, f"{dedupe_summary} {raw_method[:500]}"),
        )

        if not all([summary_embedding, raw_method_embedding, madl_embedding, main_vector]):
            logger.warning("Skipping method due to incomplete embedding generation")
            return None

        timestamp = datetime.now(timezone.utc)
        doc = {
            "_id": str(uuid.uuid4()),
            "method_name": madl.get("method_name", "unknown"),
            "raw_method_code": raw_method,
            STORED_FRAMEWORK_FIELD: framework,
            STORED_LANGUAGE_FIELD: language,
            "method_documentation": madl.get("method_documentation", {}),
            "summary_embedding": summary_embedding,
            "raw_method_embedding": raw_method_embedding,
            "madl_embedding": madl_embedding,
            "main_vector": main_vector,
            "created_at": timestamp,
            "updated_at": timestamp,
            "CreatedAt": timestamp,
            "popularity": 0.0,
            "Popularity": 0.0,
            "deleted_at": None,
        }
        return doc

    except Exception as exc:
        logger.error(f"Error processing method: {exc}", exc_info=True)
        return None


async def process_methods_batch(
    method_entries: List[Dict[str, str | None]],
    batch_size: int = 3,
) -> List[Dict[str, Any]]:
    results = []
    effective_batch_size = max(1, batch_size)

    for i in range(0, len(method_entries), effective_batch_size):
        batch = method_entries[i : i + effective_batch_size]
        batch_tasks = [
            process_single_method(
                entry["raw_method"],
                framework=entry.get("framework"),
                language=entry.get("language"),
            )
            for entry in batch
        ]
        try:
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=False)
            valid_results = [result for result in batch_results if result is not None]
            results.extend(valid_results)
            logger.info(
                f"Processed batch {i // effective_batch_size + 1}: {len(valid_results)} valid methods"
            )
        except Exception as exc:
            logger.error(f"Error processing batch: {exc}", exc_info=True)
            continue

    return results


async def _read_dataframe(file: UploadFile, file_content: bytes) -> pd.DataFrame:
    buffer = io.BytesIO(file_content)
    if file.filename.endswith(".csv"):
        return await asyncio.to_thread(pd.read_csv, buffer)

    return await asyncio.to_thread(pd.read_excel, buffer)


@router.post("/upload-methods")
async def upload_methods(
    file: UploadFile = File(...),
    framework: str | None = Form(None),
    language: str | None = Form(None),
    _: str = Depends(rate_limit_dependency),
    principal: dict = Depends(verify_api_key),
):
    """
    Upload and process automation methods from CSV/XLSX.

    Optimizations:
    - Parallel MADL generation + embeddings
    - Batched processing with concurrency control
    - Dedupe verification before expensive embedding
    - Full pipeline parallelization
    """
    Metrics.UPLOAD_COUNT.inc()

    try:
        validate_file_format(file.filename, allowed_extensions=[".csv", ".xlsx"])
    except FileValidationError:
        raise

    try:
        file_content = await file.read()
        validate_file_size(len(file_content))
        df = await _read_dataframe(file, file_content)
        df = df.astype(str).replace(["NaN", "nan", pd.NA], "")
    except FileValidationError:
        raise
    except Exception as exc:
        logger.error(f"File parsing error: {exc}")
        raise ValidationError(f"Failed to parse file: {exc}", field="file")

    normalized_default_framework = normalize_framework(framework) if framework is not None else None
    if framework is not None and not normalized_default_framework:
        raise ValidationError(
            "framework must be one of: playwright, selenium, cypress, appium",
            field="framework",
        )

    normalized_default_language = normalize_language(language) if language is not None else None
    if language is not None and not normalized_default_language:
        raise ValidationError(
            "language must be either python or javascript",
            field="language",
        )

    if "Raw Method" not in df.columns:
        raise ValidationError("File must contain 'Raw Method' column", field="Raw Method")

    method_entries = _build_method_entries(
        df,
        default_framework=normalized_default_framework,
        default_language=normalized_default_language,
    )

    if not method_entries:
        return {
            "status": "success",
            "message": "No valid methods found in file",
            "methods_processed": 0,
            "methods_inserted": 0,
        }

    logger.info(f"Processing {len(method_entries)} raw methods")

    try:
        processed_docs = await process_methods_batch(
            method_entries,
            batch_size=min(settings.MAX_CONCURRENT_LLM_CALLS, 8),
        )

        if not processed_docs:
            return {
                "status": "success",
                "message": "No unique methods after deduplication",
                "methods_processed": len(method_entries),
                "methods_inserted": 0,
            }

        col = get_methods_collection()
        result = await col.insert_many(processed_docs, ordered=False)
        cache_clear()

        await log_api_call(
            endpoint="/api/upload-methods",
            method="POST",
            user=principal,
            payload={
                "filename": file.filename,
                "methods_processed": len(method_entries),
                "framework": normalized_default_framework,
                "language": normalized_default_language,
            },
            extra={"methods_inserted": len(processed_docs)},
        )

        logger.info(f"Successfully inserted {len(processed_docs)} methods")
        return {
            "status": "success",
            "message": f"Successfully ingested {len(processed_docs)} unique automation methods",
            "methods_processed": len(method_entries),
            "methods_inserted": len(processed_docs),
            "inserted_ids": [str(inserted_id) for inserted_id in result.inserted_ids],
        }

    except DatabaseError:
        raise
    except Exception as exc:
        logger.error(f"Unexpected error during upload: {exc}", exc_info=True)
        raise DatabaseError(f"Upload failed: {exc}", operation="upload_methods")
