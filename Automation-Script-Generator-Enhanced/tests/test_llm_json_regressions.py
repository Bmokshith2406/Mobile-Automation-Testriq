import pytest

from app.core import llm_json
from app.models.cir import AssertionType, LocatorStrategy
from app.services.build_helpers.assert_extractor import AssertActionExtractor


class StubExecutor:
    def __init__(self, response_text: str):
        self.response_text = response_text

    async def run(self, prompt: str, *, purpose: str, use_cache: bool = True, config=None):
        return self.response_text


@pytest.mark.asyncio
async def test_generate_json_recovers_key_value_output_without_braces(monkeypatch):
    monkeypatch.setattr(
        llm_json,
        "_executor",
        StubExecutor(
            "\n".join(
                [
                    "assert_type: element_is_visible",
                    "locator_strategy: text",
                    "locator_value: Dashboard",
                    "expected_value: null",
                    "confidence: 94",
                ]
            )
        ),
    )

    parsed = await llm_json.generate_json(
        "prompt",
        purpose="assertion_extraction",
        use_cache=False,
    )

    assert parsed == {
        "assert_type": "element_is_visible",
        "locator_strategy": "text",
        "locator_value": "Dashboard",
        "expected_value": None,
        "confidence": 94,
    }


@pytest.mark.asyncio
async def test_assert_extractor_accepts_key_value_output_without_braces(monkeypatch):
    monkeypatch.setattr(
        llm_json,
        "_executor",
        StubExecutor(
            "\n".join(
                [
                    "assert_type: element_is_visible",
                    "locator_strategy: css",
                    "locator_value: #dashboard",
                    "expected_value: null",
                    "confidence: 96",
                ]
            )
        ),
    )

    assertion = await AssertActionExtractor().extract(
        intent='Verify "Dashboard" is visible',
        expected="Dashboard is visible",
        matched_script=None,
        use_cache=False,
    )

    assert assertion is not None
    assert assertion.assert_type == AssertionType.element_is_visible
    assert assertion.locator is not None
    assert assertion.locator.locator_strategy == LocatorStrategy.css
    assert assertion.locator.locator_value == "#dashboard"
