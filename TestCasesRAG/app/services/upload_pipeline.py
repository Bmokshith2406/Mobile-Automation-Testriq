import asyncio
import io
import uuid
from datetime import datetime, timezone
from typing import List, Tuple

import pandas as pd
from fastapi import HTTPException

from app.core.analytics import log_api_call
from app.core.cache import invalidate_search_cache
from app.core.config import get_settings
from app.core.logging import logger
from app.core.metrics import Metrics
from app.db.mongo import (
    get_playwright_scripts_collection,
    get_testcase_collection,
    transaction_session,
)
from app.services.dedupe_search_helper import search_similar_testcases
from app.services.dedupe_summary import generate_dedupe_summary
from app.services.dedupe_verifier import llm_verify_duplicate
from app.services.embeddings import embed_multivector
from app.services.enrichment import get_gemini_enrichment
from app.services.script_provenance import resolve_script_provenance

settings = get_settings()
MAX_FILE_BYTES = settings.MAX_FILE_SIZE_MB * 1024 * 1024
MAX_ROWS = 100_000
PROCESS_SEMAPHORE = asyncio.Semaphore(settings.MAX_CONCURRENT_LLM_CALLS)


def validate_upload_filename(filename: str) -> None:
    safe_name = str(filename or "").strip().lower()
    if not safe_name.endswith((".csv", ".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Invalid file type. Upload CSV or XLSX.")


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = df.columns.str.strip()
    return df


def _first_non_empty(group: pd.DataFrame, column_names: List[str]) -> str:
    for column_name in column_names:
        if column_name not in group.columns:
            continue
        series = group[column_name].fillna("").astype(str).str.strip()
        non_empty = series[series != ""]
        if not non_empty.empty:
            return non_empty.iloc[0]
    return ""


async def read_dataframe_from_bytes(filename: str, contents: bytes) -> pd.DataFrame:
    if len(contents) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="File too large.")

    buffer = io.BytesIO(contents)

    try:
        if str(filename or "").lower().endswith(".csv"):
            try:
                df = pd.read_csv(
                    buffer,
                    dtype=str,
                    sep=None,
                    engine="python",
                    encoding="utf-8",
                    na_values=["", "nan", "NaN"],
                    keep_default_na=False,
                    on_bad_lines="skip",
                )
            except UnicodeDecodeError:
                buffer.seek(0)
                df = pd.read_csv(
                    buffer,
                    dtype=str,
                    sep=None,
                    engine="python",
                    encoding="latin1",
                    na_values=["", "nan", "NaN"],
                    keep_default_na=False,
                    on_bad_lines="skip",
                )
        else:
            df = pd.read_excel(buffer, dtype=str)

    except Exception as err:
        logger.error("Failed to parse uploaded file", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {err}")

    if df.shape[0] > MAX_ROWS:
        raise HTTPException(
            status_code=413,
            detail=f"File contains too many rows ({df.shape[0]}).",
        )

    df = df.fillna("")
    return _normalize_columns(df)


async def process_testcase_group(
    test_case_id: str,
    group: pd.DataFrame,
) -> Tuple[List[dict], List[dict], int, int]:
    """
    Process a single grouped test case.
    Returns (inserted_testcase_docs, inserted_script_docs, skipped_count, processed_group_count)
    """
    async with PROCESS_SEMAPHORE:
        inserted_docs: List[dict] = []
        inserted_scripts: List[dict] = []
        skipped = 0
        processed = 0

        try:
            feature = (group.get("Feature").iloc[0] if "Feature" in group.columns else "") or ""
        except Exception:
            feature = (group.iloc[0].get("Feature") if "Feature" in group.columns else "") or ""

        platform = _first_non_empty(group, ["Platform", "platform"])
        explicit_framework = _first_non_empty(group, ["Framework", "framework"])
        explicit_language = _first_non_empty(group, ["Language", "language"])

        try:
            description = (
                group.get("Test Case Description").iloc[0]
                if "Test Case Description" in group.columns
                else (group.get("Description").iloc[0] if "Description" in group.columns else "")
            ) or ""
            prerequisites = (
                group.get("Pre-requisites").iloc[0]
                if "Pre-requisites" in group.columns
                else (group.get("Prerequisites").iloc[0] if "Prerequisites" in group.columns else "")
            ) or ""

            script_col = None
            for candidate in ("Playwright Scripts", "Playwright Script"):
                if candidate in group.columns:
                    script_col = candidate
                    break

            if not script_col:
                logger.error("Empty Playwright Script (no column)", extra={"test_case_id": test_case_id})
                skipped += 1
                return inserted_docs, inserted_scripts, skipped, processed

            script_series = group[script_col].fillna("").astype(str).str.strip()
            non_empty_scripts = script_series[script_series != ""]

            if non_empty_scripts.empty:
                logger.error("Empty Playwright Script", extra={"test_case_id": test_case_id})
                skipped += 1
                return inserted_docs, inserted_scripts, skipped, processed

            raw_script = non_empty_scripts.iloc[0]
            resolved_framework, resolved_language = resolve_script_provenance(
                raw_script,
                explicit_framework=explicit_framework,
                explicit_language=explicit_language,
                platform=platform,
                legacy_default_framework="playwright",
            )

        except Exception:
            logger.error(
                "Metadata/script extraction failed",
                extra={"test_case_id": test_case_id},
                exc_info=True,
            )
            skipped += 1
            return inserted_docs, inserted_scripts, skipped, processed

        try:
            step_no_col = next((c for c in ("Step No.", "Step No", "StepNo") if c in group.columns), None)
            test_step_col = next((c for c in ("Test Step", "TestStep") if c in group.columns), None)
            expected_col = next((c for c in ("Expected Result", "Expected") if c in group.columns), None)

            steps_rows = []
            for _, row in group.iterrows():
                step_no_raw = (row.get(step_no_col) if step_no_col else "") or ""
                test_step = (row.get(test_step_col) if test_step_col else "") or ""
                expected = (row.get(expected_col) if expected_col else "") or ""
                if not str(test_step).strip():
                    continue

                try:
                    step_no = str(int(float(step_no_raw))) if str(step_no_raw).strip() else ""
                except Exception:
                    step_no = str(step_no_raw).strip()

                formatted = f"Step {step_no}: {test_step}" if step_no else str(test_step)
                if expected and str(expected).strip():
                    formatted += f" -> Expected: {expected}"
                steps_rows.append((step_no, formatted))

            try:
                steps_rows.sort(key=lambda s: (int(s[0]) if str(s[0]).isdigit() else 10**9))
            except Exception:
                pass

            steps_combined = "\n\n".join([formatted for _, formatted in steps_rows])
        except Exception:
            steps_combined = ""

        try:
            dedupe_query = await generate_dedupe_summary(feature, description, steps_combined)
            top_hits = await search_similar_testcases(query=dedupe_query, limit=3)
            is_duplicate = await llm_verify_duplicate(
                candidate={"Feature": feature, "Description": description, "Steps": steps_combined},
                top_matches=top_hits,
            )
            if is_duplicate:
                skipped += 1
                logger.info("Dedupe skip", extra={"test_case_id": test_case_id})
                return inserted_docs, inserted_scripts, skipped, processed
        except Exception:
            logger.error("Dedupe failed - continuing", exc_info=True)

        try:
            enrichment = await get_gemini_enrichment(description, feature, steps_combined)
            summary = enrichment.get("summary", "") if enrichment else ""
            keywords = enrichment.get("keywords", []) if enrichment else []
        except Exception:
            logger.error("Enrichment failed", extra={"test_case_id": test_case_id}, exc_info=True)
            summary = ""
            keywords = []

        try:
            loop = asyncio.get_running_loop()
            if asyncio.iscoroutinefunction(embed_multivector):
                desc_emb, steps_emb, summary_emb, main_vector = await embed_multivector(
                    description=description,
                    steps=steps_combined,
                    summary=summary,
                )
            else:
                desc_emb, steps_emb, summary_emb, main_vector = await loop.run_in_executor(
                    None,
                    lambda: embed_multivector(
                        description=description,
                        steps=steps_combined,
                        summary=summary,
                    ),
                )

            def to_list(value):
                try:
                    return value.tolist()
                except Exception:
                    return list(value) if hasattr(value, "__iter__") else value

            desc_emb = to_list(desc_emb or [])
            steps_emb = to_list(steps_emb or [])
            summary_emb = to_list(summary_emb or [])
            main_vector = to_list(main_vector or [])

        except Exception:
            logger.error("Embedding failed", extra={"test_case_id": test_case_id}, exc_info=True)
            desc_emb = steps_emb = summary_emb = main_vector = []

        testcase_id = str(uuid.uuid4())
        script_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        testcase_doc = {
            "_id": testcase_id,
            "Test Case ID": test_case_id,
            "Feature": feature,
            "Test Case Description": description,
            "Pre-requisites": prerequisites,
            "Steps": steps_combined,
            "TestCaseSummary": summary,
            "TestCaseKeywords": keywords,
            "Platform": platform or resolved_framework,
            "script_framework": resolved_framework,
            "script_language": resolved_language,
            "desc_embedding": desc_emb,
            "steps_embedding": steps_emb,
            "summary_embedding": summary_emb,
            "main_vector": main_vector,
            "playwright_script_id": script_id,
            "CreatedAt": now,
            "Popularity": 0.0,
        }

        script_doc = {
            "_id": script_id,
            "testcase_id": test_case_id,
            "testcase_object_id": testcase_id,
            "script": raw_script,
            "framework": resolved_framework,
            "language": resolved_language,
            "created_at": now,
            "updated_at": now,
        }

        inserted_docs.append(testcase_doc)
        inserted_scripts.append(script_doc)
        processed += 1

        return inserted_docs, inserted_scripts, skipped, processed


async def process_upload_bytes(
    filename: str,
    contents: bytes,
    current_user: dict | None = None,
    audit_endpoint: str = "/api/upload",
) -> dict:
    validate_upload_filename(filename)

    col_testcases = get_testcase_collection()
    col_scripts = get_playwright_scripts_collection()
    df = await read_dataframe_from_bytes(filename, contents)

    col_map = {column.lower(): column for column in df.columns}

    def get_col(name_variants: List[str]):
        for variant in name_variants:
            if variant.lower() in col_map:
                return col_map[variant.lower()]
        return None

    tcid_col = get_col(["Test Case ID", "test case id", "test_case_id"])
    if not tcid_col:
        raise HTTPException(status_code=400, detail="Missing 'Test Case ID' column.")

    script_col = get_col(["Playwright Scripts", "Playwright Script"])
    if not script_col:
        raise HTTPException(status_code=400, detail="Missing mandatory column: Playwright Scripts")

    df[tcid_col] = df[tcid_col].astype(str).str.strip().replace("", pd.NA).ffill()
    df = df.loc[df[tcid_col].notna() & (df[tcid_col].str.strip().str.upper() != "NA")]

    grouped = df.groupby(tcid_col)
    paired_docs: List[Tuple[dict, dict]] = []
    skipped = 0
    total_groups = 0
    tasks = []

    for test_case_id, group in grouped:
        total_groups += 1
        tasks.append((test_case_id, group))

    logger.info("Starting upload", extra={"groups": total_groups, "filename": filename})

    results = []
    chunk_size = 200

    for index in range(0, len(tasks), chunk_size):
        chunk = tasks[index:index + chunk_size]
        logger.info(
            "Processing chunk",
            extra={
                "chunk_start": index,
                "chunk_size": len(chunk),
                "total_groups": total_groups,
                "filename": filename,
            },
        )

        try:
            chunk_tasks = [
                process_testcase_group(test_case_id, group)
                for test_case_id, group in chunk
            ]
            chunk_results = await asyncio.gather(*chunk_tasks, return_exceptions=True)

            for result in chunk_results:
                if isinstance(result, Exception):
                    logger.error("Group processor failed", exc_info=True)
                    continue
                results.append(result)
        except Exception:
            logger.error("Chunk execution failed", exc_info=True)

    for result in results:
        if not result:
            continue

        try:
            docs, scripts, skipped_inc, _processed_inc = result

            if len(docs) != len(scripts):
                logger.error(
                    "Docs and scripts count mismatch",
                    extra={"docs": len(docs), "scripts": len(scripts)},
                )
                continue

            for doc, script in zip(docs, scripts):
                paired_docs.append((doc, script))

            skipped += skipped_inc
        except Exception:
            logger.error("Unexpected result from group processor", exc_info=True)

    result_payload = {
        "testcases_inserted": 0,
        "scripts_inserted": 0,
        "duplicates_skipped": skipped,
        "total_groups": total_groups,
    }

    if not paired_docs:
        logger.info("Upload completed", extra={**result_payload, "filename": filename})
        if current_user:
            try:
                await log_api_call(
                    endpoint=audit_endpoint,
                    method="POST",
                    user=current_user,
                    payload={"filename": filename},
                    extra=result_payload,
                )
            except Exception:
                pass
        return result_payload

    try:
        batch_size = 500
        inserted_tc = 0
        inserted_sc = 0

        for index in range(0, len(paired_docs), batch_size):
            batch = paired_docs[index:index + batch_size]
            batch_tc = [item[0] for item in batch]
            batch_sc = [item[1] for item in batch]

            async with transaction_session() as session:
                res_tc = await col_testcases.insert_many(
                    batch_tc,
                    ordered=False,
                    session=session,
                )
                res_sc = await col_scripts.insert_many(
                    batch_sc,
                    ordered=False,
                    session=session,
                )

            inserted_tc += len(res_tc.inserted_ids)
            inserted_sc += len(res_sc.inserted_ids)

        result_payload = {
            "testcases_inserted": inserted_tc,
            "scripts_inserted": inserted_sc,
            "duplicates_skipped": skipped,
            "total_groups": total_groups,
        }

        Metrics.record_upload(inserted_tc)
        await invalidate_search_cache(reason="upload")

        logger.info("Upload completed", extra={**result_payload, "filename": filename})

        if current_user:
            try:
                await log_api_call(
                    endpoint=audit_endpoint,
                    method="POST",
                    user=current_user,
                    payload={"filename": filename},
                    extra=result_payload,
                )
            except Exception:
                pass

        return result_payload

    except Exception as err:
        logger.error("Mongo insert failed", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error storing data: {err}")
