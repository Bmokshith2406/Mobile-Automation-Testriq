from typing import Any, Dict, List
from fastapi import APIRouter, Body, Depends, HTTPException

from app.core.cache import get_search_cache, set_search_cache
from app.core.config import get_settings
from app.core.errors import ProductionError
from app.core.logging import logger
from app.core.analytics import log_api_call
from app.core.metrics import Metrics
from app.core.security import verify_api_key

from app.db.validation import TestCaseValidator
from app.db.mongo import get_testcase_collection
from app.models.schemas import SearchResponse, SearchRequest, SearchResultItem

from app.services.embeddings import embed_text
from app.services.expansion import normalize_query, expand_query
from app.services.ranking import build_candidates, select_final_results

# FINAL LLM RERANKER
from app.services.finalRanking import final_llm_rerank

router = APIRouter()
settings = get_settings()


def _normalize_optional_text(value: Any) -> str | None:
    try:
        normalized = str(value or "").strip()
    except Exception:
        return None

    return normalized or None


def _normalize_optional_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []

    normalized: list[str] = []
    for value in values:
        try:
            text = str(value or "").strip()
        except Exception:
            text = ""

        if text:
            normalized.append(text)

    return list(dict.fromkeys(normalized))


def _matches_requested_filters(
    document: dict,
    *,
    feature_filter: str | None,
    tags_filter: list[str],
    priority_filter: str | None,
    platform_filter: str | None,
) -> bool:
    doc_feature = _normalize_optional_text(document.get("Feature"))
    doc_priority = _normalize_optional_text(document.get("Priority"))
    doc_platform = _normalize_optional_text(document.get("Platform"))

    raw_tags = document.get("Tags") or []
    if isinstance(raw_tags, list):
        doc_tags = {str(tag or "").strip() for tag in raw_tags if str(tag or "").strip()}
    else:
        doc_tags = set()

    if feature_filter and doc_feature != feature_filter:
        return False

    if priority_filter and doc_priority != priority_filter:
        return False

    if platform_filter and doc_platform != platform_filter:
        return False

    if tags_filter and not all(tag in doc_tags for tag in tags_filter):
        return False

    return True


# -------------------------------------------------------------------
# SEARCH API
# -------------------------------------------------------------------

@router.post("/search", response_model=SearchResponse)
async def search_test_cases(
    payload: SearchRequest = Body(...),
    current_user: dict = Depends(verify_api_key),
):

    col = get_testcase_collection()

    try:
        raw_query = TestCaseValidator.validate_query(str(payload.query or ""))
    except ProductionError as err:
        raise HTTPException(status_code=400, detail=err.error_message)

    try:
        feature_filter = _normalize_optional_text(payload.feature)
    except Exception:
        feature_filter = None

    try:
        tags_filter = _normalize_optional_list(payload.tags)
    except Exception:
        tags_filter = []

    try:
        priority_filter = _normalize_optional_text(payload.priority)
    except Exception:
        priority_filter = None

    try:
        platform_filter = _normalize_optional_text(payload.platform)
    except Exception:
        platform_filter = None

    try:
        ranking_variant = (payload.ranking_variant or "A").upper()
    except Exception:
        ranking_variant = "A"

    filter_key = "::".join(
        [
            f"feature={feature_filter or ''}",
            f"tags={','.join(tags_filter)}",
            f"priority={priority_filter or ''}",
            f"platform={platform_filter or ''}",
            f"rank={ranking_variant}",
        ]
    )
    cache_key = f"{raw_query}::{filter_key}"

    # ================================================================
    # CACHE HIT
    # ================================================================
    try:
        cached = await get_search_cache(cache_key)
    except Exception:
        cached = None

    if cached:
        logger.info(f"Cache hit: '{raw_query}'")
        Metrics.record_search(cached.get("results_count", 0))
        return SearchResponse(**{**cached, "from_cache": True})

    # ================================================================
    # STEP 1 — Normalize & expand
    # ================================================================

    try:
        normalized = await normalize_query(raw_query)
    except Exception:
        normalized = raw_query

    try:
        if settings.QUERY_EXPANSION_ENABLED:
            expansions = await expand_query(
                normalized,
                n=settings.QUERY_EXPANSIONS
            )
        else:
            expansions = [normalized]
    except Exception:
        expansions = [normalized]

    if not isinstance(expansions, list):
        expansions = [normalized]

    try:
        all_expansions = list(dict.fromkeys([normalized] + expansions))
    except Exception:
        all_expansions = [normalized]

    try:
        combined_query = " ".join(all_expansions)
    except Exception:
        combined_query = normalized

    logger.info(f"Normalized   : {normalized}")
    logger.info(f"Expansions   : {all_expansions}")
    logger.info(f"Combined vec : {combined_query}")
    logger.info(
        "Requested filters",
        extra={
            "feature": feature_filter,
            "tags": tags_filter,
            "priority": priority_filter,
            "platform": platform_filter,
        },
    )

    # ================================================================
    # STEP 2 — Embed query
    # ================================================================
    try:
        query_vector = embed_text(combined_query)
    except Exception:
        logger.error("Embedding failure", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Embedding computation failed",
        )

    # ================================================================
    # STEP 3 — Mongo vector search
    # ================================================================
    try:
        search_spec: Dict[str, Any] = {
            "index": settings.VECTOR_INDEX_NAME,
            "path": "main_vector",
            "queryVector": query_vector,
            "numCandidates": 300 if (tags_filter or priority_filter or platform_filter) else 150,
            "limit": max(settings.CANDIDATES_TO_RETRIEVE * 4, settings.CANDIDATES_TO_RETRIEVE),
        }

        if feature_filter:
            search_spec["filter"] = {
                "Feature": {"$eq": feature_filter}
            }

        pipeline = [
            {"$vectorSearch": search_spec},
            {"$project": {
                "score": {"$meta": "vectorSearchScore"},
                "document": "$$ROOT",
            }},
        ]
    except Exception as err:
        logger.error(f"Pipeline assembly failed: {err}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Search pipeline failed",
        )

    try:
        search_results = await col.aggregate(
            pipeline
        ).to_list(length=settings.CANDIDATES_TO_RETRIEVE)

    except Exception:
        logger.error("Mongo vector search failure", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Vector search failed",
        )

    if tags_filter or priority_filter or platform_filter:
        search_results = [
            result
            for result in search_results
            if _matches_requested_filters(
                result.get("document", {}) or {},
                feature_filter=feature_filter,
                tags_filter=tags_filter,
                priority_filter=priority_filter,
                platform_filter=platform_filter,
            )
        ]

    # ================================================================
    # NO RESULTS
    # ================================================================
    if not search_results:

        empty = {
            "query": raw_query,
            "feature_filter": feature_filter,
            "results_count": 0,
            "results": [],
            "ranking_variant": ranking_variant,
        }

        try:
            await set_search_cache(cache_key, empty)
        except Exception:
            pass

        Metrics.record_search(0)
        return SearchResponse(**{
            **empty,
            "from_cache": False,
        })

    # ================================================================
    # STEP 4 — MULTI-SIM + INITIAL GEMINI RANKING
    # ================================================================
    try:
        candidates = build_candidates(
            raw_query=raw_query,
            all_expansions=all_expansions,
            query_vector=query_vector,
            search_results=search_results,
        )
    except Exception as err:
        logger.error("Mongo vector search failure", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Scoring failed",
        )

    try:
        final_list = await select_final_results(
            raw_query=raw_query,
            candidates=candidates,
            ranking_variant=ranking_variant,
            use_gemini_rerank=settings.GEMINI_RERANK_ENABLED,
            final_results=settings.FINAL_RESULTS,
        )
    except Exception as err:
        logger.error(f"Final candidate selection failed: {err}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Result ranking failed",
        )

    # ================================================================
    # STEP 5 — RESPONSE MAPPING
    # ================================================================
    response_items: List[SearchResultItem] = []

    try:
        total = max(len(final_list), 1)
    except Exception:
        total = 1

    for rank, c in enumerate(final_list or [], start=1):
        try:
            # local probability calc — WILL BE OVERWRITTEN by final LLM stage
            rank_weight = (total - rank + 1) / total
            norm_sim = float(c.get("local_score_norm", 0.0))

            score_pct = round(
                norm_sim * (0.6 + 0.4 * rank_weight) * 100,
                2,
            )

            payload_doc = c.get("payload", {}) or {}

            response_items.append(
                SearchResultItem(
                    id=str(payload_doc.get("_id") or payload_doc.get("id")),
                    probability=score_pct,
                    test_case_id=payload_doc.get("Test Case ID", "NA"),
                    feature=payload_doc.get("Feature", "N/A"),
                    description=payload_doc.get("Test Case Description", ""),
                    prerequisites=payload_doc.get("Pre-requisites", ""),
                    steps=payload_doc.get("Steps", ""),
                    summary=payload_doc.get("TestCaseSummary", ""),
                    keywords=payload_doc.get("TestCaseKeywords", []),
                    tags=payload_doc.get("Tags", []),
                    priority=payload_doc.get("Priority"),
                    platform=payload_doc.get("Platform"),

                   
                    playwright_script_id=(
                        payload_doc.get("playwright_script_id")
                        or payload_doc.get("PlaywrightScriptId")
                        or payload_doc.get("playwrightScriptId")
                        or payload_doc.get("script_id")
                        or payload_doc.get("ScriptID")
                    ),
                    script_framework=payload_doc.get("script_framework"),
                    script_language=payload_doc.get("script_language"),
                )
            )

        except Exception:
            continue

    # ================================================================
    # STEP 5.5 — FINAL INTENT-ONLY LLM RERANK + REAL PROBABILITY
    # ================================================================
    try:
        response_items = await final_llm_rerank(
            query=raw_query,
            results=response_items
            # top_k auto-read from settings.TOP_K
        )
    except Exception:
        logger.error(
            "Final LLM ranking failed — keeping base ordering",
            exc_info=True
        )

    # ================================================================
    # STEP 5.6 — FORCE FINAL ORDER BY PROBABILITY (DESC)
    # ================================================================
    try:
        response_items.sort(
            key=lambda x: (x.probability or 0),
            reverse=True
        )
    except Exception:
        pass

    # ================================================================
    # STEP 6 — CACHE + AUDIT
    # ================================================================
    result = {
        "query": raw_query,
        "feature_filter": feature_filter,
        "results_count": len(response_items),
        "results": response_items,
        "ranking_variant": ranking_variant,
    }

    try:
        await set_search_cache(cache_key, result)
    except Exception:
        pass

    Metrics.record_search(len(response_items))

    try:
        await log_api_call(
            endpoint="/api/search",
            method="POST",
            user=current_user,
            payload=payload.dict(),
            extra={
                "results_count": len(response_items),
                "ranking_variant": ranking_variant,
            },
        )
    except Exception:
        pass

    return SearchResponse(**{
        **result,
        "from_cache": False,
    })
