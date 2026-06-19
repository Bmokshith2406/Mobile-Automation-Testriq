import asyncio

from app.core.config import get_settings
from app.core.logging import logger
from app.llm.client import LLMClientManager

settings = get_settings()

DUPLICATE_TOKEN = "DUPLICATE"


def _get_llm_manager() -> LLMClientManager:
    return LLMClientManager.get_instance()


# -------------------------------------------------------
# LLM: Test case duplicate verifier
# -------------------------------------------------------

async def llm_verify_duplicate(
    candidate: dict,
    top_matches: list,
) -> bool:
    """
    LLM determines if incoming test case matches ANY candidate result
    in functional intent + workflow steps.

    Returns:
        True  -> DUPLICATE
        False -> UNIQUE
    """

    # -------------------------------------------------------
    # Basic short-circuit
    # -------------------------------------------------------

    try:
        if not candidate or not top_matches:
            return False
    except Exception:
        return False
    llm_manager = _get_llm_manager()

    if not llm_manager.available:
        return False

    # -------------------------------------------------------
    # Prompt build
    # -------------------------------------------------------

    try:

        existing_blocks = ""

        for i, match in enumerate(top_matches[:3], start=1):

            doc = match.get("document", {})

            existing_blocks += f"""
CASE {i}
Feature: {doc.get('Feature', '')}
Description: {doc.get('Test Case Description', '')}
Steps:
{doc.get('Steps', '')}
-----------
"""

        prompt = settings.Dedupe_Verification_Prompt.format(
            new_feature=candidate.get("Feature", ""),
            new_description=candidate.get("Description", ""),
            new_steps=candidate.get("Steps", ""),
            existing_blocks=existing_blocks,
        )

    except Exception as err:
        logger.exception(f"Dedupe prompt build failed: {err}")
        return False

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
        text = (text or "").strip().upper()

        if not text:
            return False

        if DUPLICATE_TOKEN in text.split():
            return True

        if "UNIQUE" in text:
            return False

    except Exception as e:

        logger.warning(
            f"Dedupe verification failed: {e}"
        )

    return False
