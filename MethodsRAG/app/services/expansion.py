# app/services/query_expansion.py

import asyncio
from typing import List

from app.core.config import get_settings
from app.core.logging import logger
from app.core.gemini_client import get_gemini_client
from app.services.gemini_semaphore import run_gemini_call

settings = get_settings()


# -------------------------------------------------------
# LIGHT NORMALIZER — BASELINE-COMPATIBLE
# -------------------------------------------------------
async def normalize_query(query: str) -> str:
    """
    Light spelling/grammar cleanup only.
    Does NOT rewrite intent or enforce strict constraints.
    """

    try:
        if not settings.QUERY_EXPANSION_ENABLED or not settings.GOOGLE_API_KEY:
            return str(query).strip()
    except Exception:
        return str(query).strip()

    try:
        model = await get_gemini_client()

        if not model:
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
            return str(query).strip()

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
            logger.warning(f"Gemini normalization API call failed: {err}")
            return str(query).strip()

        # ------------------------------------------------
        # Parse result
        # ------------------------------------------------
        try:
            normalized = (response.text or "").strip()
        except Exception as err:
            logger.warning(f"Gemini normalization response parse failed: {err}")
            return str(query).strip()

        # ------------------------------------------------
        # Rate limit compliance
        # ------------------------------------------------
        try:
            await asyncio.sleep(settings.GEMINI_RATE_LIMIT_SLEEP)
        except Exception:
            pass

        result = normalized.replace('"', "").strip()

        if result:
            return result

        return str(query).strip()

    except Exception as e:
        logger.warning(f"normalize_query failed: {e}")
        return str(query).strip()


# -------------------------------------------------------
# EXPANSION — EXACT BASELINE BEHAVIOR
# -------------------------------------------------------
async def expand_query(
    normalized_query: str,
    n: int = 6,
) -> List[str]:

    try:
        if not settings.QUERY_EXPANSION_ENABLED or not settings.GOOGLE_API_KEY:
            return [normalized_query]
    except Exception:
        return [normalized_query]

    try:
        model = await get_gemini_client()

        if not model:
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
            logger.warning(f"Gemini expansion API call failed: {err}")
            return [normalized_query]

        # ------------------------------------------------
        # Parse response
        # ------------------------------------------------
        try:
            text = (response.text or "").strip()
        except Exception as err:
            logger.warning(f"Gemini expansion response parse failed: {err}")
            return [normalized_query]

        try:
            parts = [
                p.strip()
                for p in text.replace("\n", ",").split(",")
                if p.strip()
            ]
        except Exception:
            parts = []

        # ------------------------------------------------
        # Baseline dedupe logic
        # ------------------------------------------------
        expansions = [normalized_query]

        for p in parts:
            try:
                if p.lower() not in map(str.lower, expansions):
                    expansions.append(p)
            except Exception:
                continue

        # ------------------------------------------------
        # Rate limit compliance
        # ------------------------------------------------
        try:
            await asyncio.sleep(settings.GEMINI_RATE_LIMIT_SLEEP)
        except Exception:
            pass

        try:
            return expansions[:n]
        except Exception:
            return expansions

    except Exception as e:
        logger.warning(f"expand_query failed: {e}")
        return [normalized_query]