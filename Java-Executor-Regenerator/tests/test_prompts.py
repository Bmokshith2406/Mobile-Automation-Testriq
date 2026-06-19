from app.core.prompts import (
    ALL_PROMPT_NAMES,
    PROMPT_BUILDERS,
    STATIC_PROMPTS,
    build_action_classifier_prompt,
    build_click_extractor_prompt,
    build_fallback_repair_prompt,
    build_repair_explanation_prompt,
    build_step_verifier_prompt,
    clip_for_prompt,
)


def test_prompt_registry_contains_every_live_prompt():
    expected = {
        "health_llm_ping",
        "action_classifier",
        "extract_click",
        "extract_type",
        "extract_select",
        "extract_assert",
        "extract_dialog",
        "step_verifier",
        "step_modifier",
        "fallback_repair",
        "fallback_structure_retry",
        "repair_explanation",
    }

    assert set(ALL_PROMPT_NAMES) == expected
    assert set(PROMPT_BUILDERS) | set(STATIC_PROMPTS) == expected


def test_clip_for_prompt_truncates_to_limit():
    clipped = clip_for_prompt("x" * 120, 32)

    assert len(clipped) <= 32
    assert clipped.endswith("[truncated]")


def test_step_verifier_prompt_caps_large_sections():
    prompt = build_step_verifier_prompt(
        verification_mode="INTENT_PLUS_REFERENCE",
        intent="verify checkout total is visible " * 20,
        matched_script="await page.locator('x').click()\n" * 400,
        generated_code="await page.locator('y').click()\n" * 400,
        error_message="Timeout waiting for selector " * 80,
        failure_history=["await page.click('bad')\n" * 120] * 5,
    )

    assert len(prompt) < 7000
    assert "Verify whether GENERATED CODE" in prompt
    assert "Previous failed attempts" in prompt


def test_fallback_repair_prompt_caps_dom_and_code():
    prompt = build_fallback_repair_prompt(
        step_intent="click submit",
        current_code="await page.locator('button').click()\n" * 300,
        error_text="Timeout 5000ms exceeded\n" * 120,
        dom_snapshot="<button>Submit</button>\n" * 500,
    )

    assert len(prompt) < 5000
    assert "Return Python function body code only." in prompt
    assert "DOM snapshot" in prompt


def test_extractor_prompts_use_single_line_contract():
    prompt = build_click_extractor_prompt(
        step_intent="Click submit",
        original_code='await page.click("#submit")',
        error_message="Timeout",
        dom_snapshot="<button>Submit</button>",
    )

    assert "one line only" in prompt.lower()
    assert 'click:<strategy>("<value>")' in prompt.lower()


def test_action_classifier_prompt_uses_compact_contract():
    prompt = build_action_classifier_prompt(
        step_intent="Click save button",
        original_code='await page.get_by_role("button", name="Save").click()',
        error_type="LOCATOR_NOT_FOUND",
    )

    assert "Return exactly one word" in prompt
    assert len(prompt) < 2000


def test_repair_explanation_prompt_is_compact():
    prompt = build_repair_explanation_prompt(
        step_id="checkout__step_4",
        step_intent="click submit checkout",
        original_code="await page.click('#submit')\n" * 200,
        repaired_code="await page.get_by_role('button', name='Submit').click()\n" * 200,
        error_text="Timeout waiting for selector\n" * 100,
        dom_snapshot="<button>Submit</button>\n" * 500,
    )

    assert "Explain why an automated" in prompt
    assert len(prompt) < 4500
