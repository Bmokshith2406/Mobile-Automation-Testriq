import re
from typing import Tuple, List, Dict, Any

from app.core.config import get_settings
from app.core.logging import logger
from app.services.keywords import extract_keywords, build_fallback_summary
from app.llm.client import LLMClientManager


settings = get_settings()


def _get_llm_manager() -> LLMClientManager:
    return LLMClientManager.get_instance()


# -------------------------------------------------------
# Clean LLM text output
# -------------------------------------------------------

def _parse_llm_enrichment_text(text: str) -> Tuple[str, List[str]]:

    summary = ""
    keywords: List[str] = []

    collecting_summary = False
    summary_lines: List[str] = []

    try:

        if not text or not isinstance(text, str):
            return "", []

        for line in text.splitlines():

            try:

                l = line.strip()
                lower = l.lower()

                if lower.startswith("summary:"):
                    collecting_summary = True
                    raw = l.split(":", 1)[1].strip()
                    if raw:
                        summary_lines.append(raw)
                    continue

                if lower.startswith("keywords:"):

                    collecting_summary = False

                    raw_kw = l.split(":", 1)[1]

                    keywords = [
                        re.sub(r"^[\-\*\d\.\)\s]+", "", k.strip())
                        for k in raw_kw.split(",")
                        if len(k.strip()) >= 2
                    ]

                    continue

                if collecting_summary and l:
                    summary_lines.append(l)

            except Exception:
                continue

        if summary_lines:
            summary = " ".join(summary_lines)
            summary = " ".join(summary.split())[:900]

        if not summary:
            parts = [p.strip() for p in text.split("\n\n") if p.strip()]
            if parts:
                summary = parts[0][:800]

        if not keywords:
            keywords = extract_keywords(text, max_keywords=15)

        keywords = [
            k for k in keywords
            if not str(k).lower().startswith("keywords:")
        ]

        keywords = list(dict.fromkeys(keywords))[:20]

        return summary.strip(), keywords

    except Exception:
        return "", []


# -------------------------------------------------------
# LLM enrichment entrypoint
# -------------------------------------------------------

async def get_llm_enrichment(
    test_case_description: str,
    feature: str,
    steps: str = "",
) -> Dict[str, Any]:
    llm_manager = _get_llm_manager()

    description_text = (test_case_description or "").strip()
    steps_text = (steps or "").strip()

    fallback_summary = build_fallback_summary(
        description_text,
        steps_text,
        max_sentences=2,
    )

    fallback_keywords = extract_keywords(
        (description_text + " " + steps_text + " " + fallback_summary).strip(),
        max_keywords=15,
    )

    # -------------------------------------------------------
    # LLM disabled
    # -------------------------------------------------------

    if not llm_manager.available:
        return {
            "summary": fallback_summary,
            "keywords": fallback_keywords,
        }

    # -------------------------------------------------------
    # Prompt
    # -------------------------------------------------------

    try:

        prompt = settings.TestCase_Enrichment_Prompt.format(
            feature=feature,
            description_text=description_text,
            steps_text=steps_text
        )

    except Exception as err:

        logger.warning(f"LLM enrichment prompt build failed: {err}")

        return {
            "summary": fallback_summary,
            "keywords": fallback_keywords,
        }

    try:
        text = await llm_manager.generate_text(
            prompt=prompt,
            retries=settings.LLM_RETRIES,
            timeout=settings.LLM_TIMEOUT_SECONDS,
            temperature=0.0,
        )

        summary, keywords = _parse_llm_enrichment_text(text)

        if not summary:
            summary = fallback_summary

        if not keywords or len(keywords) < 3:
            keywords = list(dict.fromkeys(
                (keywords or []) + fallback_keywords
            ))[:15]

        return {
            "summary": summary,
            "keywords": keywords,
        }

    except Exception as e:

        logger.warning(
            f"LLM enrichment failed: {e}"
        )

        return {
            "summary": fallback_summary,
            "keywords": fallback_keywords,
        }


async def get_gemini_enrichment(
    test_case_description: str,
    feature: str,
    steps: str = "",
) -> Dict[str, Any]:
    """Backward-compatible alias for older imports."""
    return await get_llm_enrichment(test_case_description, feature, steps)
