from __future__ import annotations

import json
import logging
from typing import Any, Dict
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


LOG = logging.getLogger(__name__)


class BaseLLMProvider:
    provider_name = "unknown"

    def __init__(self, settings):
        self.settings = settings
        self.model_name = ""
        self.available = False

    def generate_text(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        timeout: float | None = None,
    ) -> str:
        raise NotImplementedError

    def close(self) -> None:
        return None


class NullLLMProvider(BaseLLMProvider):
    provider_name = "none"

    def generate_text(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        timeout: float | None = None,
    ) -> str:
        raise RuntimeError("No LLM provider available")


def parse_text_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                if item.strip():
                    parts.append(item.strip())
                continue
            if isinstance(item, dict):
                text = (
                    item.get("text")
                    or item.get("content")
                    or item.get("output_text")
                    or item.get("value")
                )
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        return "\n".join(parts).strip()
    if isinstance(value, dict):
        for key in ("text", "content", "output_text", "response", "generated_text"):
            text = parse_text_value(value.get(key))
            if text:
                return text
    return ""


def post_json(
    url: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    timeout: float,
) -> Dict[str, Any]:
    request = Request(
        url=url,
        headers=headers,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            if not body.strip():
                return {}
            return json.loads(body)
    except HTTPError as err:
        try:
            payload_text = err.read().decode("utf-8")
        except Exception:
            payload_text = str(err)
        raise RuntimeError(f"HTTP {err.code}: {payload_text}") from err
    except URLError as err:
        raise RuntimeError(f"Network error: {err}") from err
