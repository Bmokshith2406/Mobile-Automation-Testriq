from typing import List, Dict, Any
import re

from app.core.config import get_settings
from app.core.logging import logger
from app.core.gemini_client import get_gemini_client
from app.services.gemini_semaphore import run_gemini_call

settings = get_settings()


# --------------------------------------------------------
# Line normalization
# --------------------------------------------------------
def safe_parse_lines(text: str) -> List[str]:
    """
    Extract meaningful non-empty lines only.
    Cleans numbering / bullets automatically.
    Robust against varied Gemini formatting.
    """

    lines: List[str] = []

    try:
        if not text or not isinstance(text, str):
            return lines

        for l in text.splitlines():

            try:
                l = l.strip()
            except Exception:
                continue

            if not l:
                continue

            try:
                l = re.sub(r"^[\-\*\d\.\)\s]+", "", l)
            except Exception:
                pass

            if l:
                lines.append(l)

    except Exception as err:
        logger.warning(f"safe_parse_lines failed: {err}")
        return []

    return lines


# --------------------------------------------------------
# GEMINI RERANK — METHOD SEARCH
# --------------------------------------------------------
async def rerank_with_gemini(
    query: str,
    candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:

    # ------------------------------------------------
    # Safety gate
    # ------------------------------------------------

    try:
        if not settings.GEMINI_RERANK_ENABLED or not settings.GOOGLE_API_KEY:
            return candidates
    except Exception:
        return candidates

    try:
        if not candidates:
            return candidates
    except Exception:
        return candidates


    # ------------------------------------------------
    # Get shared Gemini client
    # ------------------------------------------------

    model = await get_gemini_client()

    if not model:
        logger.warning("Gemini client unavailable")
        return candidates


    # ------------------------------------------------
    # Build prompt
    # ------------------------------------------------

    try:
        prompt = settings.Results_ReRanking_Prompt.format(
            query=query
        )
    except Exception as err:
        logger.warning(f"Prompt formatting failed: {err}")
        return candidates


    # ------------------------------------------------
    # Attach METHOD candidates
    # ------------------------------------------------

    for c in candidates:

        try:

            brief = (
                c.get("summary")
                or c.get("method_documentation", {}).get("summary", "")
                or ""
            )

            brief = brief.strip().replace("\n", " ")[:220]

            prompt += (
                f"{c['_id']} | Method: {c.get('method_name','N/A')} | "
                f"Summary: {brief}\n"
            )

        except Exception as err:

            logger.warning(
                f"Prompt composition failed for candidate {c.get('_id')}: {err}"
            )


    # ------------------------------------------------
    # Gemini call
    # ------------------------------------------------

    try:
        response = await run_gemini_call(
                lambda: model.models.generate_content(
                    model=settings.GEMINI_LLM_MODEL,
                    contents=prompt
                )
            )
    except Exception as err:
        logger.warning(f"Gemini API call failed: {err}")
        return candidates


    try:
        text = (response.text or "").strip()
    except Exception as err:
        logger.warning(f"Gemini response parsing failed: {err}")
        return candidates


    # ------------------------------------------------
    # Output parsing
    # ------------------------------------------------

    lines = safe_parse_lines(text)

    ordered_ids: List[str] = []

    for l in lines:

        try:
            cid = l.split()[0].strip(".,-_ ")
            if cid:
                ordered_ids.append(cid)

        except Exception:
            continue


    # ------------------------------------------------
    # Rebuild ranked results
    # ------------------------------------------------

    try:
        id_to_candidate = {
            str(c["_id"]): c
            for c in candidates
        }
    except Exception:
        id_to_candidate = {}


    ordered: List[Dict[str, Any]] = []
    seen_ids = set()


    for cid in ordered_ids:

        try:
            if cid in id_to_candidate and cid not in seen_ids:
                ordered.append(id_to_candidate[cid])
                seen_ids.add(cid)
        except Exception:
            continue


    # ------------------------------------------------
    # Append leftovers preserving stability
    # ------------------------------------------------

    for cand in candidates:

        try:
            if str(cand.get("_id")) not in seen_ids:
                ordered.append(cand)
        except Exception:
            continue


    return ordered