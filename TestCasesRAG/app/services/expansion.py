import re
from typing import List

from app.core.config import get_settings
from app.core.logging import logger
from app.llm.client import LLMClientManager

settings = get_settings()


def _get_llm_manager() -> LLMClientManager:
    return LLMClientManager.get_instance()


# -------------------------------------------------------
# LIGHT NORMALIZER — BASELINE-COMPATIBLE
# -------------------------------------------------------
async def normalize_query(query: str) -> str:
    llm_manager = _get_llm_manager()

    try:
        if not settings.QUERY_EXPANSION_ENABLED or not llm_manager.available:
            return query.strip()
    except Exception:
        return str(query).strip()

    # ------------------------------------------------
    # Prompt build
    # ------------------------------------------------
    try:

        prompt = settings.Query_Normalization_Prompt.format(
            query=query
        )

    except Exception as err:

        logger.warning(f"Query normalization prompt formatting failed: {err}")
        return query.strip()

    try:
        normalized = await llm_manager.generate_text(
            prompt=prompt,
            retries=settings.LLM_RETRIES,
            timeout=settings.LLM_TIMEOUT_SECONDS,
            temperature=0.0,
        )

        result = normalized.replace('"', "").strip()

        if result:
            return result

        return query.strip()

    except Exception as e:

        logger.warning(f"normalize_query failed: {e}")

        return query.strip()


# -------------------------------------------------------
# EXPANSION — EXACT BASELINE BEHAVIOR
# -------------------------------------------------------
async def expand_query(
    normalized_query: str,
    n: int = 6,
) -> List[str]:
    llm_manager = _get_llm_manager()

    try:
        if not settings.QUERY_EXPANSION_ENABLED or not llm_manager.available:
            return [normalized_query]
    except Exception:
        return [normalized_query]

    # ------------------------------------------------
    # Prompt build
    # ------------------------------------------------
    try:

        prompt = settings.Query_Expansion_Prompt.format(
            normalized_query=normalized_query,
            n=settings.QUERY_EXPANSIONS
        )

    except Exception as err:

        logger.warning(f"Query expansion prompt formatting failed: {err}")

        return [normalized_query]

    try:
        text = await llm_manager.generate_text(
            prompt=prompt,
            retries=settings.LLM_RETRIES,
            timeout=settings.LLM_TIMEOUT_SECONDS,
            temperature=0.0,
        )

        parts = [
            p.strip()
            for p in text.replace("\n", ",").split(",")
            if p.strip()
        ]

        expansions = [normalized_query]

        for p in parts:

            try:
                if p.lower() not in map(str.lower, expansions):
                    expansions.append(p)
            except Exception:
                continue

        return expansions[:n]

    except Exception as e:

        logger.warning(f"expand_query failed: {e}")

        return [normalized_query]
