# app/core/llm_json.py

from typing import Dict, Optional, Any
import ast
import json
import logging
import re

from app.core.llm_executor import get_llm_executor, LLMExecutor
from app.core.llm import LLMConfig
from app.core.config import get_settings

logger = logging.getLogger("llm.json")

_executor: Optional[LLMExecutor] = None


def _get_executor() -> LLMExecutor:
    """
    Lazily fetch the centralized LLM executor (singleton-safe).
    """
    global _executor

    if _executor is None:
        _executor = get_llm_executor()

    return _executor


# --------------------------------------------------
# INTERNAL: JSON EXTRACTION (ROBUST)
# --------------------------------------------------

def _extract_json_block(text: Optional[str], max_chars: int) -> Optional[str]:
    """
    Extract the first valid JSON object or array from raw LLM output.
    """
    if not text or not isinstance(text, str):
        return None

    text = text.strip()

    # Remove markdown fences
    text = (
        text.replace("```json", "")
        .replace("```", "")
        .strip()
    )

    start_obj = text.find("{")
    start_arr = text.find("[")

    if start_obj == -1 and start_arr == -1:
        return None

    start = (
        start_obj
        if start_obj != -1 and (start_arr == -1 or start_obj < start_arr)
        else start_arr
    )

    # Try JSONDecoder.raw_decode first (handles braces in strings correctly)
    try:
        _, end = json.JSONDecoder().raw_decode(text, start)
        return text[start:end]
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback: brace counting
    open_char = text[start]
    close_char = "}" if open_char == "{" else "]"
    depth = 0
    for i in range(start, len(text)):
        if text[i] == open_char:
            depth += 1
        elif text[i] == close_char:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

    return None


def _coerce_scalar(value: str) -> Any:
    raw = str(value or "").strip().rstrip(",")
    if not raw:
        return ""

    lowered = raw.lower()
    if lowered in {"null", "none"}:
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False

    if re.fullmatch(r"-?\d+", raw):
        try:
            return int(raw)
        except Exception:
            pass
    if re.fullmatch(r"-?\d+\.\d+", raw):
        try:
            return float(raw)
        except Exception:
            pass

    try:
        parsed = ast.literal_eval(raw)
        if isinstance(parsed, (dict, list, str, int, float, bool)) or parsed is None:
            return parsed
    except Exception:
        pass

    return raw.strip("\"'")


def _extract_key_value_mapping(text: Optional[str], max_chars: int) -> Optional[Dict[str, Any]]:
    """
    Recover a dict from common non-JSON LLM outputs such as:

        assert_type: element_is_visible
        locator_strategy: text
        locator_value: Dashboard
        expected_value: null
        confidence: 92

    This is intentionally conservative:
    - requires at least two structured pairs
    - ignores free-form prose lines
    """
    if not text or not isinstance(text, str):
        return None

    normalized = text.strip()[:max_chars]
    normalized = normalized.replace("```json", "").replace("```", "").strip()
    if not normalized:
        return None

    pairs: Dict[str, Any] = {}
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]

    if len(lines) == 1 and lines[0].count(":") > 1:
        segments = [segment.strip() for segment in re.split(r",\s*(?=[A-Za-z_][A-Za-z0-9_ ]*\s*[:=])", lines[0]) if segment.strip()]
    else:
        segments = lines

    for segment in segments:
        cleaned = re.sub(r"^[\-\*\d\.\)\s]+", "", segment).strip()
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_ ]{0,63})\s*[:=]\s*(.+)$", cleaned)
        if not match:
            continue

        key = match.group(1).strip().lower().replace(" ", "_")
        value = match.group(2).strip()
        if not key:
            continue

        pairs[key] = _coerce_scalar(value)

    return pairs if len(pairs) >= 2 else None


# --------------------------------------------------
# PUBLIC API
# --------------------------------------------------

async def generate_json(
    prompt: str,
    *,
    purpose: str,
    use_cache: bool = True,
    schema: Optional[Dict[str, Any]] = None,
) -> Optional[Any]:
    """
    Execute an LLM prompt and return parsed JSON.

    Guarantees:
    - Returns dict or list on success
    - Returns None on ANY failure
    - Never raises
    - CIR-safe and extractor-safe
    - Cache-aware

    Args:
        schema: Optional JSON Schema dict. When provided, the provider uses
                structured output mode (Gemini response_schema / OpenAI
                json_schema) guaranteeing schema-conformant JSON back.
    """

    settings = get_settings()
    max_chars = getattr(settings, "MAX_JSON_CHARS", 5000)

    executor = _get_executor()

    config: Optional[LLMConfig] = None
    if schema is not None:
        config = LLMConfig(
            temperature=getattr(settings, "LLM_TEMPERATURE", 0.1),
            top_p=getattr(settings, "LLM_TOP_P", 0.95),
            max_output_tokens=getattr(settings, "MAX_OUTPUT_TOKENS", 2048),
            timeout_seconds=getattr(settings, "LLM_TIMEOUT_SECONDS", 60),
            response_schema=schema,
        )

    try:
        raw = await executor.run(
            prompt,
            purpose=purpose,
            use_cache=use_cache,
            config=config,
        )
    except Exception as e:
        logger.error(
            "LLM execution error | purpose=%s | cache=%s | error=%s",
            purpose,
            use_cache,
            str(e),
            exc_info=True,
        )
        return None

    if raw is None:
        logger.warning("LLM returned no response | purpose=%s | cache=%s", purpose, use_cache)
        return None

    json_text = _extract_json_block(raw, max_chars)

    if not json_text:
        recovered = _extract_key_value_mapping(raw, max_chars)
        if recovered is not None:
            logger.info(
                "Recovered structured key-value output without JSON braces | purpose=%s | cache=%s",
                purpose,
                use_cache,
            )
            return recovered
        logger.warning("No JSON block found in LLM output | purpose=%s | cache=%s", purpose, use_cache)
        return None

    try:
        parsed = json.loads(json_text)
    except Exception as e:
        sanitized = re.sub(r",\s*(\}|\])", r"\1", json_text)
        try:
            parsed = json.loads(sanitized)
        except Exception:
            try:
                parsed = ast.literal_eval(json_text)
            except Exception:
                logger.warning(
                    "Invalid JSON extracted | purpose=%s | cache=%s | error=%s",
                    purpose,
                    use_cache,
                    str(e),
                )
                return None

    if not isinstance(parsed, (dict, list)):
        logger.warning(
            "JSON root is not object or array | purpose=%s | cache=%s | type=%s",
            purpose,
            use_cache,
            type(parsed).__name__,
        )
        return None

    return parsed





