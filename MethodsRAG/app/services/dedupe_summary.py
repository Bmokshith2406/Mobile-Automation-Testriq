import asyncio

from app.core.config import get_settings
from app.core.logging import logger
from app.core.gemini_client import get_gemini_client
from app.services.gemini_semaphore import run_gemini_call


settings = get_settings()


# -------------------------------------------------------
# Gemini: 10–12-word dedupe summary generator (METHOD)
# -------------------------------------------------------

async def generate_method_dedupe_summary(
    raw_method: str,
) -> str:
    """
    Generates STRICT 10–12-word functional-purpose summary from raw
    Automation method source code used only for semantic dedupe.
    """

    # -------------------------------------------------------
    # Normalize input
    # -------------------------------------------------------

    try:
        raw_method_text = (raw_method or "").strip()
    except Exception:
        raw_method_text = ""

    fallback = " ".join(raw_method_text.split())[:80]

    if not raw_method_text:
        return fallback

    # -------------------------------------------------------
    # Gemini disabled → fallback
    # -------------------------------------------------------

    if not settings.GOOGLE_API_KEY:
        return fallback

    # -------------------------------------------------------
    # Prompt build
    # -------------------------------------------------------

    try:
        prompt = settings.Dedupe_Summary_Prompt.format(
            raw_method=raw_method_text
        )
    except Exception as err:
        logger.warning(f"Method dedupe prompt build failed: {err}")
        return fallback

    # -------------------------------------------------------
    # Get shared Gemini client
    # -------------------------------------------------------

    model = await get_gemini_client()

    if not model:
        logger.warning("Gemini client unavailable")
        return fallback

    # -------------------------------------------------------
    # Gemini execution with retries
    # -------------------------------------------------------

    for attempt in range(max(1, settings.GEMINI_RETRIES)):

        try:
            response = await run_gemini_call(
                lambda: model.models.generate_content(
                    model=settings.GEMINI_LLM_MODEL,
                    contents=prompt
                )
            )

            try:
                text = (response.text or "").strip()
            except Exception:
                text = ""

            words = text.split()

            # STRICT 10–12 words
            if len(words) >= 10:
                return " ".join(words[:12]).strip()

        except Exception as err:

            logger.warning(
                f"Method dedupe summary attempt {attempt + 1} failed: {err}"
            )

            try:
                await asyncio.sleep(settings.GEMINI_RATE_LIMIT_SLEEP)
            except Exception:
                pass

    logger.warning("Method dedupe summary fallback triggered")

    return fallback
