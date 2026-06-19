import pytest

from app.core import llm_json


class StubExecutor:
    async def run_modifier(self, prompt: str):
        return "\n".join(
            [
                "assert_type: element_is_visible",
                "locator_strategy: text",
                "locator_value: Dashboard",
                "expected_value: null",
                "confidence: 91",
            ]
        )


@pytest.mark.asyncio
async def test_generate_json_recovers_key_value_output_without_braces(monkeypatch):
    monkeypatch.setattr(llm_json, "_executor", StubExecutor())

    parsed = await llm_json.generate_json("prompt")

    assert parsed == {
        "assert_type": "element_is_visible",
        "locator_strategy": "text",
        "locator_value": "Dashboard",
        "expected_value": None,
        "confidence": 91,
    }
