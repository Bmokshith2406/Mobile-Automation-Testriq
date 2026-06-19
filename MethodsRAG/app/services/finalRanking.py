# app/services/finalRanking.py

from typing import List
import re

from app.core.config import get_settings
from app.core.logging import logger
from app.models.schemas import SearchResultItem
from app.core.gemini_client import get_gemini_client
from app.services.gemini_semaphore import run_gemini_call

settings = get_settings()


# ----------------------------------------------------
# Utilities
# ----------------------------------------------------

def _safe_parse_lines(text: str) -> List[str]:
    """
    Extract meaningful non-empty lines from LLM output.
    Safely removes bullets / numbering WITHOUT destroying UUIDs.
    """

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
# FINAL LLM METHOD RERANKER
# ----------------------------------------------------

async def final_llm_rerank(
    query: str,
    results: List[SearchResultItem],
    top_k: int | None = None,
) -> List[SearchResultItem]:

    try:
        top_k = top_k or settings.TOP_K
    except Exception:
        top_k = settings.TOP_K

    # ------------------------------------------------
    # Early exit safety gate
    # ------------------------------------------------
    try:
        if (
            not settings.GEMINI_RERANK_ENABLED
            or not settings.GOOGLE_API_KEY
            or not results
            or len(results) <= 1
        ):
            return results[:top_k]
    except Exception:
        return results[:top_k]

    try:

        # ------------------------------------------------
        # Get shared Gemini client
        # ------------------------------------------------
        model = await get_gemini_client()

        if not model:
            logger.warning("Gemini client unavailable")
            return results[:top_k]

        # ------------------------------------------------
        # Build base prompt
        # ------------------------------------------------
        try:
            prompt = settings.Final_Ranking_Prompt.format(
                query=query,
                top_k=top_k,
            )
        except Exception:
            logger.exception("Failed to build reranking prompt")
            return results[:top_k]

        # ------------------------------------------------
        # Attach MADL metadata
        # ------------------------------------------------
        for r in results:

            try:

                prompt += f"""
-------------------------------------------------
ID: {r.id}
Method Name: {r.method_name}

Summary:
{r.summary}

Description:
{r.description}

Intent:
{r.intent}

Parameters:
{", ".join([f"{k}: {v}" for k, v in (r.params or {}).items()])}

Keywords:
{", ".join(r.keywords or [])}
-------------------------------------------------
"""

            except Exception:
                continue

        # ------------------------------------------------
        # Gemini call (through semaphore)
        # ------------------------------------------------
        try:
            response = await run_gemini_call(
                lambda: model.models.generate_content(
                    model=settings.GEMINI_LLM_MODEL,
                    contents=prompt
                )
            )
        except Exception:
            logger.exception("Gemini rerank call failed")
            return results[:top_k]

        try:
            raw_output = (response.text or "").strip()
        except Exception:
            logger.exception("Failed reading Gemini response")
            return results[:top_k]

        ranked_items = []

        # ------------------------------------------------
        # Parse Gemini output
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
                continue

        # ------------------------------------------------
        # Ranking sanity
        # ------------------------------------------------
        if not ranked_items:
            return results[:top_k]

        ranked_items = ranked_items[:top_k]

        try:
            id_map = {str(r.id): r for r in results}
        except Exception:
            logger.exception("Failed building ID map")
            return results[:top_k]

        final_results: List[SearchResultItem] = []

        for _id, score in ranked_items:

            try:

                if _id in id_map:
                    item = id_map[_id]
                    item.probability = round(score, 2)
                    final_results.append(item)

            except Exception:
                continue

        # ------------------------------------------------
        # Fallback fill
        # ------------------------------------------------
        if len(final_results) < top_k:

            for r in results:

                try:

                    if r not in final_results:
                        r.probability = round(r.probability or 50.0, 2)
                        final_results.append(r)

                    if len(final_results) == top_k:
                        break

                except Exception:
                    continue

        try:
            logger.info(
                f"Gemini method rerank completed with {len(final_results)} results."
            )
        except Exception:
            pass

        return final_results

    except Exception:
        logger.exception("Uncaught reranking failure")
        return results[:top_k]