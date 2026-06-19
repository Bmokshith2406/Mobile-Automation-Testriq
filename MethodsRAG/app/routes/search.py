import json
from typing import Any, Dict, List

from fastapi import APIRouter, Body, Depends, HTTPException

from app.core.analytics import log_api_call
from app.core.cache import cache_get, cache_set
from app.core.config import get_settings
from app.core.logging import logger
from app.core.rate_limiter import rate_limit_dependency
from app.core.security import verify_api_key
from app.core.soft_delete import active_document_filter
from app.core.validation import validate_query
from app.db.mongo import get_methods_collection
from app.models.schemas import SearchRequest, SearchResponse, SearchResultItem
from app.services.code_provenance import STORED_FRAMEWORK_FIELD, STORED_LANGUAGE_FIELD
from app.services.embeddings import embed_text
from app.services.expansion import expand_query, normalize_query
from app.services.finalRanking import final_llm_rerank
from app.services.ranking import build_candidates, select_final_results
from app.core.metrics import Metrics

router = APIRouter()
settings = get_settings()


def _build_cache_key(payload: SearchRequest, raw_query: str, ranking_variant: str) -> str:
    cache_payload = {
        "query": raw_query,
        "ranking_variant": ranking_variant,
        "owner": payload.owner,
        "reusable": payload.reusable,
        "keywords": sorted([keyword.lower() for keyword in (payload.keywords or [])]),
    }
    return json.dumps(cache_payload, sort_keys=True)


def _matches_filters(payload_doc: Dict[str, Any], search_payload: SearchRequest) -> bool:
    md = payload_doc.get("method_documentation", {}) or {}

    if search_payload.owner and md.get("owner") != search_payload.owner:
        return False

    if search_payload.reusable is not None and bool(md.get("reusable")) != search_payload.reusable:
        return False

    if search_payload.keywords:
        existing_keywords = {str(keyword).strip().lower() for keyword in md.get("keywords", [])}
        requested_keywords = {keyword.strip().lower() for keyword in search_payload.keywords if keyword.strip()}
        if requested_keywords and not requested_keywords.intersection(existing_keywords):
            return False

    return True


def _serialize_result_item(item: SearchResultItem) -> dict[str, Any]:
    return item.model_dump()


@router.post("/search", response_model=SearchResponse)
async def search_methods(
    payload: SearchRequest = Body(...),
    _: str = Depends(rate_limit_dependency),
    principal: dict = Depends(verify_api_key),
):
    """
    Search for automation methods using vector search + ranking.

    Query is normalized, expanded, embedded, and searched using MongoDB Atlas vector search.
    Results are reranked using LLM for final relevance ordering.
    """
    Metrics.SEARCH_COUNT.inc()
    col = get_methods_collection()

    raw_query = validate_query(payload.query)
    ranking_variant = payload.ranking_variant.upper()
    cache_key = _build_cache_key(payload, raw_query, ranking_variant)

    cached = cache_get(cache_key)
    if cached:
        logger.info(f"Cache hit: '{raw_query}'")
        return SearchResponse(**{**cached, "from_cache": True})

    normalized = await normalize_query(raw_query)
    expansions = (
        await expand_query(normalized, n=settings.QUERY_EXPANSIONS)
        if settings.QUERY_EXPANSION_ENABLED
        else [normalized]
    )
    all_expansions = list(dict.fromkeys([normalized] + expansions))
    combined_query = " ".join(all_expansions)

    logger.info(f"Normalized   : {normalized}")
    logger.info(f"Expansions   : {all_expansions}")
    logger.info(f"Combined vec : {combined_query}")

    query_vector = embed_text(combined_query)
    if not query_vector:
        raise HTTPException(status_code=500, detail="Embedding computation failed")

    filter_requested = bool(payload.owner or payload.reusable is not None or payload.keywords)
    retrieve_limit = settings.CANDIDATES_TO_RETRIEVE * 4 if filter_requested else settings.CANDIDATES_TO_RETRIEVE

    pipeline = [
        {
            "$vectorSearch": {
                "index": settings.VECTOR_INDEX_NAME,
                "path": "main_vector",
                "queryVector": query_vector,
                "numCandidates": max(retrieve_limit * 10, 150),
                "limit": retrieve_limit,
            }
        },
        {
            "$project": {
                "score": {"$meta": "vectorSearchScore"},
                "document": "$$ROOT",
            }
        },
        {"$match": active_document_filter("document.")},
    ]

    try:
        search_results = await col.aggregate(pipeline).to_list(length=retrieve_limit)
    except Exception:
        logger.exception("Mongo vector search failure")
        raise HTTPException(status_code=500, detail="Vector search failed")

    if filter_requested:
        search_results = [
            result
            for result in search_results
            if _matches_filters(result.get("document", {}) or {}, payload)
        ]

    if not search_results:
        empty = {
            "query": raw_query,
            "results_count": 0,
            "results": [],
            "ranking_variant": ranking_variant,
        }
        cache_set(cache_key, empty)
        return SearchResponse(**{**empty, "from_cache": False})

    try:
        candidates = build_candidates(
            raw_query=raw_query,
            all_expansions=all_expansions,
            query_vector=query_vector,
            search_results=search_results,
        )
    except Exception as err:
        logger.exception(f"Candidate build failed: {err}")
        raise HTTPException(status_code=500, detail="Scoring failed")

    try:
        final_list = await select_final_results(
            raw_query=raw_query,
            candidates=candidates,
            ranking_variant=ranking_variant,
            use_gemini_rerank=settings.GEMINI_RERANK_ENABLED,
            final_results=settings.FINAL_RESULTS,
        )
    except Exception as err:
        logger.exception(f"Final candidate selection failed: {err}")
        raise HTTPException(status_code=500, detail="Result ranking failed")

    response_items: List[SearchResultItem] = []
    total = max(len(final_list), 1)

    for rank, candidate in enumerate(final_list, start=1):
        payload_doc = candidate.get("payload", {}) or {}
        md = payload_doc.get("method_documentation", {}) or {}

        rank_weight = (total - rank + 1) / total
        norm_sim = float(candidate.get("local_score_norm", 0.0))
        score_pct = round((0.6 * norm_sim + 0.4 * rank_weight) * 100, 2)

        try:
            response_items.append(
                SearchResultItem(
                    id=str(payload_doc.get("_id", "")),
                    probability=score_pct,
                    method_name=payload_doc.get("method_name", ""),
                    summary=md.get("summary", ""),
                    description=md.get("description", ""),
                    intent=md.get("intent", ""),
                    params=md.get("params", {}),
                    applies=md.get("applies", ""),
                    returns=md.get("returns", ""),
                    keywords=md.get("keywords", []),
                    owner=md.get("owner"),
                    reusable=md.get("reusable"),
                    example_usage=md.get("example_usage"),
                    raw_code=payload_doc.get("raw_method_code"),
                    framework=payload_doc.get(STORED_FRAMEWORK_FIELD) or payload_doc.get("framework"),
                    language=payload_doc.get(STORED_LANGUAGE_FIELD) or payload_doc.get("language"),
                )
            )
        except Exception:
            continue

    try:
        response_items = await final_llm_rerank(
            query=raw_query,
            results=response_items,
            top_k=settings.FINAL_RESULTS,
        )
    except Exception:
        logger.exception("Final LLM ranking failed — keeping local ordering")

    response_items.sort(key=lambda item: (item.probability or 0), reverse=True)
    serialized_results = [_serialize_result_item(item) for item in response_items]

    result = {
        "query": raw_query,
        "results_count": len(serialized_results),
        "results": serialized_results,
        "ranking_variant": ranking_variant,
    }
    cache_set(cache_key, result)

    await log_api_call(
        endpoint="/api/search",
        method="POST",
        user=principal,
        payload=payload.model_dump(),
        extra={
            "results_count": len(serialized_results),
            "ranking_variant": ranking_variant,
            "top_method_names": [item["method_name"] for item in serialized_results[:5]],
        },
    )

    return SearchResponse(**{**result, "from_cache": False})
