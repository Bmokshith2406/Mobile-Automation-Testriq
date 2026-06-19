# app/services/finalRanking.py

from typing import List
import re

from app.core.config import get_settings
from app.core.logging import logger
from app.models.schemas import SearchResultItem
from app.llm.client import LLMClientManager

settings = get_settings()


def _get_llm_manager() -> LLMClientManager:
    return LLMClientManager.get_instance()


# ----------------------------------------------------
# Utilities
# ----------------------------------------------------

def _safe_parse_lines(text: str) -> List[str]:

    lines: List[str] = []

    try:

        if not isinstance(text, str):
            return lines

        for l in text.splitlines():

            try:
                l = l.strip()
            except Exception:
                continue

            if not l:
                continue

            try:
                l = re.sub(r"^(\d+[\.\)]\s*)", "", l)
            except Exception:
                pass

            try:
                l = re.sub(r"^[\*\-]\s*", "", l)
            except Exception:
                pass

            if l:
                lines.append(l)

    except Exception:
        return []

    return lines


# ----------------------------------------------------
# FINAL LLM INTENT RANKER + REAL PROBABILITY SCORING
# ----------------------------------------------------

async def final_llm_rerank(
    query: str,
    results: List[SearchResultItem],
    top_k: int | None = None,
) -> List[SearchResultItem]:
    llm_manager = _get_llm_manager()

    try:
        top_k = top_k or settings.TOP_K
    except Exception:
        top_k = settings.TOP_K

    # ------------------------------------------------
    # HARD DEDUPE INPUT
    # ------------------------------------------------

    try:

        unique = {}

        for r in results:
            if r.id not in unique:
                unique[r.id] = r

        results = list(unique.values())

    except Exception:
        pass

    try:
        local_top_k = min(top_k or settings.TOP_K, len(results))
    except Exception:
        local_top_k = len(results)

    # ------------------------------------------------
    # Early exit
    # ------------------------------------------------

    try:

        if (
            not settings.GEMINI_RERANK_ENABLED
            or not llm_manager.available
            or not results
        ):
            return results[:top_k]

    except Exception:
        return results[:top_k]

    # ------------------------------------------------
    # Build prompt
    # ------------------------------------------------

    try:

        prompt = settings.Final_Ranking_Prompt.format(
            query=query,
            top_k=local_top_k,
        )

    except Exception:
        return results[:top_k]

    for r in results:

        try:

            prompt += f"""
-------------------------------------------------
ID: {r.id}
Feature: {r.feature}
Description: {r.description}

Prerequisites:
{r.prerequisites}

Steps:
{r.steps}

Summary:
{r.summary}

Keywords:
{", ".join(r.keywords or [])}
-------------------------------------------------
"""

        except Exception:
            pass

    try:
        raw_output = await llm_manager.generate_text(
            prompt=prompt,
            retries=settings.LLM_RETRIES,
            timeout=settings.LLM_TIMEOUT_SECONDS,
            temperature=0.0,
        )

    except Exception:

        return results[:top_k]

    ranked_items = []

    # ------------------------------------------------
    # Parse LLM response
    # ------------------------------------------------

    for line in _safe_parse_lines(raw_output):

        try:

            parts = [p.strip() for p in line.split("|")]

            if len(parts) != 2:
                continue

            _id, score_text = parts

            try:
                score = float(score_text)
            except Exception:
                continue

            score = max(0.0, min(100.0, score))

            ranked_items.append((_id, score))

        except Exception:
            pass

    # ------------------------------------------------
    # Ranking sanity
    # ------------------------------------------------

    if not ranked_items:
        return results[:top_k]

    ranked_items = ranked_items[:top_k]

    try:
        id_map = {str(r.id): r for r in results}
    except Exception:
        return results[:top_k]

    final_results: List[SearchResultItem] = []

    for _id, score in ranked_items:

        try:

            if _id in id_map:

                item = id_map[_id]

                item.probability = round(score, 2)

                final_results.append(item)

        except Exception:
            pass

    # ------------------------------------------------
    # Fallback fill
    # ------------------------------------------------

    try:
        seen_ids = set(r.id for r in final_results)
    except Exception:
        seen_ids = set()

    if len(final_results) < top_k:

        for r in results:

            try:

                if r.id not in seen_ids:

                    r.probability = round(r.probability or 50.0, 2)

                    final_results.append(r)

                    seen_ids.add(r.id)

                if len(final_results) == top_k:
                    break

            except Exception:
                pass

    # ------------------------------------------------
    # FINAL HARD DEDUPE
    # ------------------------------------------------

    try:

        unique = {}

        for r in final_results:
            if r.id not in unique:
                unique[r.id] = r

        final_results = list(unique.values())

    except Exception:
        pass

    try:
        logger.info(
            f"LLM rerank completed with {len(final_results)} results via "
            f"{llm_manager.provider_name or 'fallback'}."
        )
    except Exception:
        pass

    return final_results
