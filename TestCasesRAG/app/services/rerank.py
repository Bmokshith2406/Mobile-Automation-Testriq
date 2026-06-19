from typing import List, Dict, Any
import re

from app.core.config import get_settings
from app.core.logging import logger
from app.llm.client import LLMClientManager

settings = get_settings()


def _get_llm_manager() -> LLMClientManager:
    return LLMClientManager.get_instance()


# --------------------------------------------------------
# Line normalization
# --------------------------------------------------------
def safe_parse_lines(text: str) -> List[str]:

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
# LLM RERANK — STRING PROMPT VERSION (ID SAFE)
# --------------------------------------------------------
async def rerank_with_llm(
    query: str,
    candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    llm_manager = _get_llm_manager()

    try:

        if not settings.GEMINI_RERANK_ENABLED or not llm_manager.available:
            return candidates

    except Exception:
        return candidates

    try:
        if not candidates:
            return candidates
    except Exception:
        return candidates


    # ------------------------------------------------
    # HARD DEDUPE INPUT
    # ------------------------------------------------

    try:

        unique = {}

        for c in candidates:

            cid = str(c.get("_id"))

            if cid not in unique:
                unique[cid] = c

        candidates = list(unique.values())

    except Exception:
        pass


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


    for c in candidates:

        try:

            brief = (
                c.get("description")
                or c.get("summary")
                or ""
            )

            brief = brief.strip().replace("\n", " ")[:220]

            prompt += (
                f"{c['_id']} | Feature: {c.get('feature','N/A')} | "
                f"Desc: {brief}\n"
            )

        except Exception as err:

            logger.warning(
                f"Prompt composition failed for candidate {c.get('_id')}: {err}"
            )


    try:
        text = await llm_manager.generate_text(
            prompt=prompt,
            retries=settings.LLM_RETRIES,
            timeout=settings.LLM_TIMEOUT_SECONDS,
            temperature=0.0,
        )

    except Exception as err:

        logger.warning(f"LLM API call failed: {err}")

        return candidates


    # ------------------------------------------------
    # Output parsing
    # ------------------------------------------------

    lines = safe_parse_lines(text)

    ordered_ids: List[str] = []

    for l in lines:

        try:

            token = l.split("|")[0].strip()

            token = re.sub(r"^(id|ID|Id)\s*[:\-]?\s*", "", token)

            token = token.strip(".,-_ ")

            if token:
                ordered_ids.append(token)

        except Exception:
            continue


    # ------------------------------------------------
    # Rebuild ranked results (ID SAFE)
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

            cid = str(cand.get("_id"))

            if cid not in seen_ids:

                ordered.append(cand)

                seen_ids.add(cid)

        except Exception:
            continue


    return ordered


async def rerank_with_gemini(
    query: str,
    candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Backward-compatible alias for older imports."""
    return await rerank_with_llm(query, candidates)
