import asyncio
import random
from typing import Optional

from google import genai
from google.genai.types import GenerateContentConfig

from app.core.config import get_settings
from app.core.logging import logger
from app.core.exceptions import ExternalServiceError, TimeoutError

settings = get_settings()

_client = None
_model_name = settings.GEMINI_LLM_MODEL
_client_lock = asyncio.Lock()


async def get_gemini_client():
    """
    Returns a singleton Gemini client instance.
    Ensures initialization only once.
    """
    global _client

    if _client is not None:
        return _client

    async with _client_lock:
        if _client is not None:
            return _client

        try:
            api_key = settings.GOOGLE_API_KEY

            if not api_key:
                raise ValueError("Gemini API key not configured")

            _client = genai.Client(api_key=api_key)

            logger.info(
                f"Gemini client initialized successfully (model={_model_name})"
            )

            return _client

        except Exception as err:
            logger.critical(
                f"Gemini initialization failed: {err}",
                exc_info=True
            )
            raise ExternalServiceError(
                "Gemini",
                f"Failed to initialize: {err}"
            )


async def call_gemini_with_backoff(
    prompt: str,
    max_retries: Optional[int] = None,
    timeout_seconds: Optional[float] = None,
) -> str:
    """
    Call Gemini API with exponential backoff retry logic.
    """
    global _model_name

    if max_retries is None:
        max_retries = settings.GEMINI_RETRIES

    if timeout_seconds is None:
        timeout_seconds = settings.GEMINI_TIMEOUT

    base_delay = settings.GEMINI_RETRY_BASE_DELAY
    max_delay = settings.GEMINI_RETRY_MAX_DELAY

    last_error = None

    for attempt in range(max_retries):

        try:
            client = await get_gemini_client()

            async def _call():
                return await asyncio.to_thread(
                    lambda: client.models.generate_content(
                        model=_model_name,
                        contents=prompt,
                        config=GenerateContentConfig(
                            temperature=0.2,
                            max_output_tokens=2048
                        )
                    )
                )

            try:
                response = await asyncio.wait_for(
                    _call(),
                    timeout=timeout_seconds
                )
            except asyncio.TimeoutError:
                raise TimeoutError("Gemini", timeout_seconds)
            except Exception as e:
                exc_str = str(e).lower()
                if ("429" in exc_str or "rate" in exc_str or "quota" in exc_str) and _model_name == settings.GEMINI_LLM_MODEL:
                    logger.warning(
                        f"Quota exhausted for {_model_name}. Switching to fallback {settings.LLM_FALLBACK_MODEL}"
                    )
                    _model_name = settings.LLM_FALLBACK_MODEL
                    response = await asyncio.wait_for(
                        asyncio.to_thread(
                            lambda: client.models.generate_content(
                                model=_model_name,
                                contents=prompt,
                                config=GenerateContentConfig(
                                    temperature=0.2,
                                    max_output_tokens=2048
                                )
                            )
                        ),
                        timeout=timeout_seconds
                    )
                else:
                    raise

            if response and response.text:
                logger.debug(
                    f"Gemini call successful on attempt {attempt + 1}"
                )
                return response.text

            raise ValueError("Gemini returned empty response")

        except TimeoutError:
            raise

        except Exception as e:

            last_error = e

            logger.warning(
                f"Gemini API call failed (attempt {attempt + 1}/{max_retries}): {e}",
                extra={
                    "attempt": attempt + 1,
                    "max_retries": max_retries,
                    "error": str(e)
                }
            )

            if attempt == max_retries - 1:
                break

            delay = min(base_delay * (2 ** attempt), max_delay)
            jitter = random.uniform(0, delay * 0.1)
            sleep_time = delay + jitter

            logger.info(f"Retrying Gemini in {sleep_time:.2f}s...")
            await asyncio.sleep(sleep_time)

    error_msg = f"Gemini API failed after {max_retries} attempts: {last_error}"

    logger.error(error_msg)

    raise ExternalServiceError(
        "Gemini",
        f"Failed after {max_retries} retries: {str(last_error)}",
        retry_after=int(
            min(base_delay * (2 ** (max_retries - 1)), max_delay)
        )
    )
