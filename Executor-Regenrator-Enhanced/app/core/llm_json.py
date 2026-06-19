# app/core/llm_json.py

"""
WARNING — ARCHITECTURAL NOTICE

This module is NOT used in STEP-LEVEL REPAIR.

It exists ONLY for:
- Offline analysis
- Metadata extraction
- Non-critical JSON generation tasks

DO NOT use this for:
- Verifier logic
- Modifier logic
- Step regeneration
"""

from typing import Optional, Any
import ast
import json
import logging
import re

from app.core.llm_executor import LLMExecutor

logger = logging.getLogger("llm.json")

_executor: Optional[LLMExecutor] = None


def _get_executor() -> LLMExecutor:
    """
    Lazily fetch the centralized LLM executor (singleton-safe).
    """
    global _executor

    if _executor is None:
        _executor = LLMExecutor.get_instance()

    return _executor


# --------------------------------------------------
# INTERNAL: JSON EXTRACTION (BEST-EFFORT)
# --------------------------------------------------

def _extract_json_block(text: Optional[str], max_chars: int) -> Optional[str]:
    """
    Best-effort extraction of the first JSON object or array
    from an LLM response.

    ⚠️ This is intentionally permissive and unsafe for
    step-level repair. Use ONLY for auxiliary tasks.
    """

    if not text or not isinstance(text, str):
        return None

    text = text.strip()[:max_chars]

    # Remove markdown fences if present
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


def _extract_key_value_mapping(text: Optional[str], max_chars: int) -> Optional[dict[str, Any]]:
    if not text or not isinstance(text, str):
        return None

    normalized = text.strip()[:max_chars]
    normalized = normalized.replace("```json", "").replace("```", "").strip()
    if not normalized:
        return None

    pairs: dict[str, Any] = {}
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
        if key:
            pairs[key] = _coerce_scalar(value)

    return pairs if len(pairs) >= 2 else None


# --------------------------------------------------
# PUBLIC API (NON-CRITICAL ONLY)
# --------------------------------------------------

async def generate_json(
    prompt: str,
    *,
    max_chars: int = 5000,
) -> Optional[Any]:
    """
    Execute an LLM prompt and attempt to extract JSON.

    GUARANTEES:
    - Returns dict or list on success
    - Returns None on ANY failure
    - NEVER raises

    🚫 MUST NOT be used in:
    - Step verifier
    - Step modifier
    - CIR generation
    """

    executor = _get_executor()

    # IMPORTANT:
    # JSON generation is always treated as a MODIFIER role,
    # never verifier, and is NOT bounded for correctness.
    raw = await executor.run_modifier(prompt)

    if raw is None:
        logger.warning("LLM returned no response for JSON generation")
        return None

    json_text = _extract_json_block(raw, max_chars)

    if not json_text:
        recovered = _extract_key_value_mapping(raw, max_chars)
        if recovered is not None:
            logger.info("Recovered structured key-value output without JSON braces")
            return recovered
        logger.warning("No JSON block found in LLM output")
        return None

    try:
        parsed = json.loads(json_text)
    except Exception:
        sanitized = re.sub(r",\s*(\}|\])", r"\1", json_text)
        try:
            parsed = json.loads(sanitized)
        except Exception:
            try:
                parsed = ast.literal_eval(json_text)
            except Exception:
                logger.warning("Invalid JSON extracted from LLM output")
                return None

    if not isinstance(parsed, (dict, list)):
        logger.warning("JSON root is not object or array")
        return None

    return parsed
