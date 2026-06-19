import asyncio

from app.core.config import get_settings
from app.core.logging import logger
from app.llm.client import LLMClientManager

settings = get_settings()


def _get_llm_manager() -> LLMClientManager:
    return LLMClientManager.get_instance()


# -------------------------------------------------------
# LLM: 12-word dedupe summary generator
# -------------------------------------------------------

async def generate_dedupe_summary(
    feature: str,
    description: str,
    steps: str,
) -> str:
    """
    Generates STRICT 12-word functional-purpose summary used only
    for semantic search dedupe.
    """

    try:
        feature_text = (feature or "").strip()
        description_text = (description or "").strip()
        steps_text = (steps or "").strip()
    except Exception:
        feature_text = ""
        description_text = ""
        steps_text = ""

    # -------------------------------------------------------
    # Hard fallback → pure truncation-based text
    # -------------------------------------------------------

    fallback = " ".join(
        (description_text + " " + steps_text).split()
    )[:80]
    llm_manager = _get_llm_manager()

    # -------------------------------------------------------
    # LLM disabled -> fallback only
    # -------------------------------------------------------

    if not llm_manager.available:
        return fallback

    # -------------------------------------------------------
    # Prompt build
    # -------------------------------------------------------

    try:
        prompt = settings.Dedupe_Summary_Prompt.format(
            feature=feature_text,
            description_text=description_text,
            steps_text=steps_text,
        )
    except Exception as err:
        logger.warning(f"Dedupe prompt build failed: {err}")
        return fallback

    # -------------------------------------------------------
    # Execute via LLM manager
    # -------------------------------------------------------

    try:

        text = await asyncio.wait_for(
            llm_manager.generate_text(
                prompt=prompt,
                retries=settings.LLM_RETRIES,
                timeout=settings.LLM_TIMEOUT_SECONDS,
                temperature=0.0,
            ),
            timeout=settings.LLM_TIMEOUT_SECONDS + 2,
        )

        words = text.split()

        if len(words) >= 8:
            return " ".join(words[:12]).strip()

    except Exception as e:

        logger.warning(
            f"Dedupe summary generation failed: {e}"
        )

    return fallback
