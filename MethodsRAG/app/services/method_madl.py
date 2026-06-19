# app/services/method_madl.py

from __future__ import annotations

import ast
import json
import re
from datetime import datetime
from typing import Dict, Any

from app.core.config import get_settings
from app.core.logging import logger
from app.core.exceptions import ExternalServiceError
from app.services.keywords import extract_keywords
from app.core.gemini_client import call_gemini_with_backoff
from app.services.code_provenance import display_framework, display_language, resolve_code_provenance

settings = get_settings()


# -------------------------------------------------------
# AST Fallback Helpers
# -------------------------------------------------------

def _extract_python_signature(raw_code: str) -> str:
    """
    Extract full method signature using AST.
    """
    try:
        tree = ast.parse(raw_code)

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                params = [a.arg for a in node.args.args]
                return f"{node.name}({', '.join(params)})"

    except Exception:
        pass

    return "unknown_method()"


def _extract_javascript_signature(raw_code: str) -> str:
    patterns = [
        r"async\s+function\s+([A-Za-z_][\w$]*)\s*\(([^)]*)\)",
        r"function\s+([A-Za-z_][\w$]*)\s*\(([^)]*)\)",
        r"(?:const|let|var)\s+([A-Za-z_][\w$]*)\s*=\s*async\s*\(([^)]*)\)\s*=>",
        r"(?:const|let|var)\s+([A-Za-z_][\w$]*)\s*=\s*\(([^)]*)\)\s*=>",
    ]

    for pattern in patterns:
        match = re.search(pattern, raw_code)
        if match:
            name = match.group(1)
            params = match.group(2).strip()
            return f"{name}({params})"

    return "unknown_method()"


def _extract_signature(raw_code: str, language: str | None) -> str:
    if language == "javascript":
        signature = _extract_javascript_signature(raw_code)
        if signature != "unknown_method()":
            return signature

    signature = _extract_python_signature(raw_code)
    if signature != "unknown_method()":
        return signature

    if language == "javascript":
        return _extract_javascript_signature(raw_code)
    return signature


def _extract_python_params(raw_code: str) -> Dict[str, str]:
    """
    Extract parameter map using AST.
    """

    params = {}

    try:
        tree = ast.parse(raw_code)

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for p in node.args.args:
                    params[p.arg] = f"Parameter `{p.arg}` used by this method."

    except Exception:
        pass

    return params


def _extract_signature_params(signature: str) -> Dict[str, str]:
    match = re.search(r"\((.*)\)", signature)
    if not match:
        return {}

    params: Dict[str, str] = {}
    raw_params = match.group(1).strip()
    if not raw_params:
        return params

    for chunk in raw_params.split(","):
        name = chunk.strip()
        if not name:
            continue
        name = re.sub(r"^[.]{3}", "", name)
        name = name.split("=", 1)[0].split(":", 1)[0].strip()
        if name:
            params[name] = f"Parameter `{name}` used by this method."
    return params


def _extract_params(raw_code: str, language: str | None, signature: str) -> Dict[str, str]:
    if language != "javascript":
        params = _extract_python_params(raw_code)
        if params:
            return params
    return _extract_signature_params(signature)


# -------------------------------------------------------
# JSON Parser
# -------------------------------------------------------

def _safe_json_parse(text: str) -> Dict[str, Any]:
    """
    Safely parse Gemini JSON output.
    """

    try:
        return json.loads(text)
    except Exception:
        pass

    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        return json.loads(text[start:end])
    except Exception:
        pass

    return {}


# -------------------------------------------------------
# CORE MADL GENERATION ENTRYPOINT
# -------------------------------------------------------

async def get_method_madl(
    raw_method: str,
    *,
    framework: str | None = None,
    language: str | None = None,
) -> Dict[str, Any]:
    """
    Convert a raw automation method into MADL JSON.
    """

    raw_method = (raw_method or "").strip()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    resolved_framework, resolved_language = resolve_code_provenance(
        raw_method,
        explicit_framework=framework,
        explicit_language=language,
    )
    framework_label = display_framework(resolved_framework)
    language_label = display_language(resolved_language)
    summary_label = f"{framework_label.title()} {language_label}" if resolved_framework else "Generic automation"
    description_label = (
        f"{framework_label} {language_label} automation"
        if resolved_framework
        else "automation"
    )
    intent_label = f"{framework_label} automation" if resolved_framework else "automation"

    # -----------------------------
    # FALLBACK FROM AST
    # -----------------------------

    fallback_signature = _extract_signature(raw_method, resolved_language)
    fallback_params = _extract_params(raw_method, resolved_language, fallback_signature)
    fallback_keywords = extract_keywords(raw_method, max_keywords=15)
    if resolved_framework == "appium":
        applies = "Mobile elements, gestures, and application flows"
    else:
        applies = "Automation actions, locators, and assertions"

    owner = "QE-Core/Automation"
    if resolved_framework:
        owner = f"QE-Core/{resolved_framework.title()} Automation"

    fallback_madl = {
        "method_name": fallback_signature,
        "raw_method_code": raw_method,
        "method_documentation": {
            "summary": f"{summary_label} utility method.",
            "description": f"Generic helper function used in {description_label} workflows.",
            "reusable": True,
            "intent": f"Perform {intent_label} task.",
            "params": fallback_params,
            "applies": applies,
            "returns": "None",
            "keywords": fallback_keywords,
            "owner": owner,
            "example_usage": fallback_signature,
            "created": today,
            "last_updated": today,
        },
    }

    # -----------------------------
    # Gemini Disabled → Fallback
    # -----------------------------

    if not settings.GOOGLE_API_KEY:
        return fallback_madl

    # -----------------------------
    # Build Prompt
    # -----------------------------

    try:
        prompt = settings.Method_MADL_Prompt.format(
            framework_label=framework_label,
            language_label=language_label,
            raw_method=raw_method,
        )
    except Exception as err:
        logger.warning(f"MADL prompt build failed: {err}")
        return fallback_madl

    # ---------- -----
    # LLM Execution with exponential backoff
    # ---------- -----

    try:
        text = await call_gemini_with_backoff(prompt)
        madl = _safe_json_parse(text)

        if (
            madl
            and "method_name" in madl
            and "method_documentation" in madl
        ):

            madl["raw_method_code"] = raw_method

            md = madl["method_documentation"]

            md["created"] = md.get("created") or today
            md["last_updated"] = today

            logger.debug("MADL generation successful")
            return madl
        else:
            logger.warning("MADL generation failed - invalid JSON structure")
            return fallback_madl

    except ExternalServiceError as e:
        logger.warning(f"MADL generation external service error: {e.message}")
        return fallback_madl
    except Exception as err:
        logger.warning(f"MADL generation failed: {err}", exc_info=True)
        return fallback_madl
