# app/prompts/template_engine.py
"""
Prompt Template Engine

Provides Jinja2-based template rendering for LLM prompts
with built-in sanitization and CIR legality enforcement.
"""

import logging
from typing import Optional, Dict, Any
from pathlib import Path

from jinja2 import Environment, select_autoescape, BaseLoader, TemplateNotFound

from app.utils.sanitization import sanitize_for_prompt

logger = logging.getLogger("prompts")


class DictLoader(BaseLoader):
    """Load templates from a dictionary."""
    
    def __init__(self, templates: Dict[str, str]):
        self.templates = templates
    
    def get_source(self, environment, template):
        if template in self.templates:
            source = self.templates[template]
            return source, template, lambda: True
        raise TemplateNotFound(template)


class PromptTemplateEngine:
    """
    Template engine for LLM prompts.

    HARD GUARANTEES:
    - All prompts are CIR-legal
    - All outputs conform to CIR schema
    - No illegal combinations allowed
    - No ambiguous formats
    - No missing required fields
    """

    BUILT_IN_TEMPLATES = {

        # ============================================================
        # ACTION CLASSIFICATION
        # ============================================================
        "classification": """
Return JSON ONLY.

You are classifying a UI test step into exactly ONE action type.

The Action types that we currently accept are:
- navigate
- click
- type
- clear
- select
- assert

Probable Definitions:
- navigate → page transitions, URL changes, back/forward/refresh
- click → clicking buttons, links, icons
- type → entering text into an input field
- clear → removing or emptying text from an input field
- select → choosing from dropdowns, lists, or combo boxes
- assert → verifying a UI state or outcome

Rules:
- Choose EXACTLY ONE action type
- Choose the MOST SPECIFIC type
- Assertions verify outcomes, not interactions
- If ambiguous, prefer action over assertion
- NEVER return multiple types
- Use "clear" ONLY when the intent is to remove existing text

Examples for CLEAR:
- "Clear first name field"
- "Erase username"
- "Empty password input"
- "Reset email field"

Step intent:
{{ intent }}

Expected outcome:
{{ expected or "N/A" }}

Reference script:
{{ script or "N/A" }}

FORMAT:
{
  "action_type": "navigate | click | type | clear | select | assert",
  "confidence": 0-100,
  "reasoning": "brief explanation"
}

""",

        # ============================================================
        # CLICK LOCATOR (DYNAMIC)
        # ============================================================
        "click_locator": """
Return JSON ONLY.

Extract the click target locator for {{ profile.name }}.

Rules:
- Locator MUST be {{ profile.name }} compatible.
- You MUST follow this strict priority order (highest → lowest):
{% for strat in profile.locator_priority %}
  {{ loop.index }}. {{ strat }}
{% endfor %}

- Always choose the highest-priority reliable locator
- Use a lower-priority strategy ONLY if all higher-priority ones are unavailable or unreliable
- Do NOT invent locators
{% if "role" in profile.allowed_strategies %}
- Role locators MUST follow: role|name
{% endif %}
- If no reliable locator can be determined, return null
{{ profile.syntax_guidelines }}

Allowed locator strategies:
{% for strat in profile.allowed_strategies %}
- {{ strat }}
{% endfor %}

Forbidden strategies (DO NOT USE):
{% for strat in profile.forbidden_strategies %}
- {{ strat }}
{% endfor %}

Intent:
{{ intent }}

Reference script:
{{ script or "N/A" }}

FORMAT:
{
  "locator_strategy": "{% for strat in profile.allowed_strategies %}{{ strat }} | {% endfor %}null",
  "locator_value": null,
  "confidence": 0-100
}
""",

        # ============================================================
        # TYPE LOCATOR (DYNAMIC)
        # ============================================================
        "type_locator": """
Return JSON ONLY.

Extract the input field locator for {{ profile.name }}.

Rules:
- Locator MUST be {{ profile.name }} compatible.
- You MUST follow this strict priority order (highest → lowest):
{% for strat in profile.locator_priority %}
  {{ loop.index }}. {{ strat }}
{% endfor %}

- Always choose the highest-priority reliable locator
- Use a lower-priority strategy ONLY if higher-priority ones are unavailable
- Do NOT invent locators
- If no reliable locator can be determined, return null
{{ profile.syntax_guidelines }}

Allowed locator strategies:
{% for strat in profile.allowed_strategies %}
- {{ strat }}
{% endfor %}

Forbidden strategies (DO NOT USE):
{% for strat in profile.forbidden_strategies %}
- {{ strat }}
{% endfor %}

Allowed inference:
If intent mentions a field name like "username", "email", "password", try ONLY if higher-priority locators are unavailable:
- #username
- input[name="username"]
- input[placeholder*="username"]

Intent:
{{ intent }}

Reference script:
{{ script or "N/A" }}

FORMAT:
{
  "locator_strategy": "{% for strat in profile.allowed_strategies %}{{ strat }} | {% endfor %}null",
  "locator_value": null,
  "confidence": 0-100
}
""",

        # ============================================================
        # TYPE VALUE
        # ============================================================
        "type_value": """
Return JSON ONLY.

Extract the exact text value to type.

Rules:
- Value MUST appear verbatim in the intent or script
- Do NOT invent
- Do NOT normalize
- Preserve exact casing
- If value is missing, return null (this will trigger fallback or reclassification)

Intent:
{{ intent }}

Reference script:
{{ script or "N/A" }}

FORMAT:
{
  "value": null,
  "confidence": 0-100
}

""",

        # ============================================================
        # SELECT LOCATOR (DYNAMIC)
        # ============================================================
        "select_locator": """
Return JSON ONLY.

Extract the select/dropdown locator for {{ profile.name }}.

Rules:
- Locator MUST be {{ profile.name }} compatible.
- You MUST follow this strict priority order (highest → lowest):
{% for strat in profile.locator_priority %}
  {{ loop.index }}. {{ strat }}
{% endfor %}

- Always choose the highest-priority reliable locator
- Use a lower-priority strategy ONLY if higher-priority ones are unavailable
- Do NOT invent locators
{% if "role" in profile.allowed_strategies %}
- Role locators MUST follow: role|name
{% endif %}
- If no reliable locator can be determined, return null
{{ profile.syntax_guidelines }}

Allowed locator strategies:
{% for strat in profile.allowed_strategies %}
- {{ strat }}
{% endfor %}

Forbidden strategies (DO NOT USE):
{% for strat in profile.forbidden_strategies %}
- {{ strat }}
{% endfor %}

Intent:
{{ intent }}

Reference script:
{{ script or "N/A" }}

FORMAT:
{
  "locator_strategy": "{% for strat in profile.allowed_strategies %}{{ strat }} | {% endfor %}null",
  "locator_value": null,
  "confidence": 0-100
}
""",

        # ============================================================
        # SELECT VALUE
        # ============================================================
        "select_value": """
Return JSON ONLY.

Extract the value to select.

Rules:
- Value must be explicitly mentioned
- Do NOT invent values
- Determine the correct mode:
  - value → HTML option value
  - label → visible text
  - index → numeric index
- If no explicit value is found, return null

Intent:
{{ intent }}

Reference script:
{{ script or "N/A" }}

FORMAT:
{
  "value": null,
  "mode": "value | label | index",
  "confidence": 0-100
}
""",

        # ============================================================
        # ASSERT EXTRACTION (DYNAMIC)
        # ============================================================
        "assert_extraction": """
Return RAW JSON ONLY.
No markdown.
No backticks.
No explanation.
No prose.
No comments.
No trailing text.
The first character must be { and the last character must be }.
Do not omit the outer JSON braces.

If you output anything other than valid JSON, your response will be discarded.

You are extracting a UI assertion for {{ profile.name }}.

Allowed assertion types:
- element_is_visible
- text_equals
- text_contains
- url_contains
- title_contains
- title_equals

Rules:
- Choose the MOST specific assert_type
- You MUST follow this strict locator priority order (highest → lowest):
{% for strat in profile.locator_priority %}
  {{ loop.index }}. {{ strat }}
{% endfor %}

- Always choose the highest-priority reliable locator
- element_is_visible → requires locator, expected_value MUST be null
- text_equals → requires locator and expected_value
- text_contains → requires locator and expected_value
- url_contains → requires expected_value, locator MUST be null
- title_contains → requires expected_value, locator MUST be null
- title_equals → requires expected_value, locator MUST be null
- Do NOT invent expected values
- Do NOT invent locators
{% if "role" in profile.allowed_strategies %}
- Role locators MUST follow: role|name
{% endif %}
{{ profile.syntax_guidelines }}

Allowed locator strategies:
{% for strat in profile.allowed_strategies %}
- {{ strat }}
{% endfor %}

Forbidden strategies (DO NOT USE):
{% for strat in profile.forbidden_strategies %}
- {{ strat }}
{% endfor %}

Intent:
{{ intent }}

Expected outcome:
{{ expected or "N/A" }}

Reference script:
{{ script or "N/A" }}

Output EXACTLY this JSON shape:

{
  "assert_type": "element_is_visible | text_equals | text_contains | url_contains | title_contains | title_equals",
  "locator_strategy": "{% for strat in profile.allowed_strategies %}{{ strat }} | {% endfor %}null",
  "locator_value": null,
  "expected_value": null,
  "confidence": 0-100
}
"""
,

        # ============================================================
        # STEP DECOMPOSITION
        # ============================================================
        "step_decomposition": """
Return JSON ONLY.

Decompose this UI test step into atomic user actions.

Rules:
- Split ONLY if multiple UI interactions are clearly implied
- Preserve execution order
- Each atomic step must map to exactly ONE UI action
- Do NOT invent steps
- Do NOT add assertions
- If already atomic, return ONE item

Step:
{{ intent }}

Expected:
{{ expected or "N/A" }}

Reference script:
{{ script or "N/A" }}

FORMAT:
{
  "atomic_steps": ["..."]
}
""",

        # ============================================================
        # FRAMEWORK ROLE UPGRADE
        # ============================================================
        "framework_role_upgrade": """
You are a SAFE {{ profile.name }} LOCATOR UPGRADE ENGINE.

Your task:
- Upgrade locators to semantic role locators if supported by {{ profile.name }}
- ONLY if the upgrade is provably safe and semantically identical
- If ANY doubt exists, return the ORIGINAL code unchanged

ABSOLUTE RULES (MUST FOLLOW):
- DO NOT change action type
- DO NOT change control flow
- DO NOT change values
- DO NOT add or remove lines
- DO NOT refactor logic
- DO NOT reformat code
- DO NOT infer names or roles
- DO NOT guess accessibility
- DO NOT add comments

You MAY change the code to use role-based APIs (e.g. get_by_role, cy.get('[role=...]', etc) depending on {{ profile.name }}.

ONLY if ALL are true:
- Element maps 1-to-1 to an ARIA role
- Accessible name is explicitly present in locator
- No constraints are lost

ALLOWED upgrades (ONLY these exact patterns):
- page.locator("button:has-text('X')")
- page.locator("a:has-text('X')")
- page.locator("button").filter(has_text="X")

FORBIDDEN:
- XPath
- nth / first / last
- chained selectors
- class or id selectors
- partial / fuzzy text
- variables or expressions
- multiple locators
- attribute-heavy selectors

If no safe upgrade applies → return ORIGINAL code.

Return JSON ONLY.

FORMAT:
{
  "upgraded_code": "...",
  "changed": true | false,
  "reason": "explicit technical justification"
}

ORIGINAL CODE:
{{ raw_code }}
""",

        # ============================================================
        # STEP VERIFICATION
        # ============================================================
        "step_verification": """
You are a {{ profile.name }} STEP VERIFIER.

You are a semantic consistency and safety judge.
You MUST NOT reinterpret or redefine behavior.

PRIMARY RULE:
The CIR-defined behavior is the source of truth.
The intent is explanatory context.

────────────────────────────────────────────
HARD SEMANTIC CONSTRAINTS (NON-NEGOTIABLE)
────────────────────────────────────────────

1. TYPE and CLEAR actions MUST explicitly target the intended element.
   - Using ':focus' is FORBIDDEN
   - Using keyboard typing is FORBIDDEN
   - Inferring the target from prior actions is FORBIDDEN
   - Using key presses to clear (Backspace/Delete) is FORBIDDEN

2. CLEAR semantics:
   - Clearing means setting the input value to empty
   - Must use fill("") or equivalent direct value reset
   - Must NOT simulate keystrokes
   - Must NOT rely on focus

3. Every semantic action must operate on the intended UI element
   using an EXPLICIT locator.

4. Redundant atomic actions (e.g., click before fill) are allowed ONLY if:
   - They do NOT change the semantic meaning
   - They do NOT infer a target
   - They do NOT introduce ambiguity

5. Semantic equivalence IS allowed.
   Syntactic equivalence is NOT required.

6. If the intent implies a TYPE action:
   - The code MUST contain: locator → element → fill/type
   - It MUST NOT rely on focus

7. If the intent implies a CLEAR action:
   - The code MUST explicitly reset the field value to empty
   - It MUST use a direct fill/reset API
   - It MUST NOT use keyboard simulation

8. If any of the above rules are violated → INCORRECT

You MUST NOT propose semantic changes.
You MUST NOT reinterpret the action.
You MUST NOT change what the step does.
You may only judge correctness vs CIR intent.

────────────────────────────────────────────
LOCATOR EQUIVALENCE POLICY
────────────────────────────────────────────

You must reason SEMANTICALLY, not syntactically.

{{ profile.syntax_guidelines }}

If the generated locator:
- Clearly identifies the same UI element
- Is explicit
- Is deterministic

Then it is CORRECT.

Reject ONLY if:
- Locator is missing
- Locator is ambiguous
- Locator is hallucinated
- Locator relies on focus
- Locator infers target implicitly

────────────────────────────────────────────
CIR-LOCKED JUDGMENT RULES
────────────────────────────────────────────

- Judge correctness using the CIR-defined behavior.
- Intent is explanatory context, not authority.
- The reference script is only supporting context.
- Do NOT require Selenium-style syntax.
- Do NOT require matching the reference script.
- Do NOT penalize valid native {{ profile.name }} locators.

────────────────────────────────────────────
RESPONSE FORMAT (JSON ONLY)
────────────────────────────────────────────

{
  "verdict": "correct" | "incorrect",
  "reason": "explicit, technical explanation"
}

────────────────────────────────────────────

INTENT:
{{ intent }}

REFERENCE SCRIPT (optional):
{{ matched_script or "N/A" }}

GENERATED CODE:
{{ generated_code }}
""",

        # ============================================================
        # STEP SAFETY REPAIR
        # ============================================================
        "step_safety_repair": """
You are repairing a {{ profile.name }} STEP BODY.

This is a SAFETY-ONLY task.

ABSOLUTE RULES:
- You MUST NOT change the action type
- You MUST NOT replace actions with assertions
- You MUST NOT convert TYPE into CLEAR
- You MUST NOT convert CLEAR into TYPE
- You MUST NOT convert TYPE into ASSERT
- You MUST NOT convert CLICK into ASSERT
- You MUST NOT remove any action
- You MUST NOT add new actions
- You MUST NOT reorder actions

Allowed:
- waits
- scrolling
- visibility checks
- {{ profile.name }} API fixes
- locator repairs
- role corrections
- accessible name cleanup

VERIFIER REASON:
{{ reason or "N/A" }}

INTENT:
{{ intent }}

CURRENT STEP BODY:
{{ original_code }}

Return ONLY valid {{ profile.name }} code.
""",

        # ============================================================
        # INTENT PARAMETER CORRECTION
        # ============================================================
        "intent_parameter_correction": """
You are a **CIR-SAFE PARAMETER CORRECTION ENGINE** for UI automation code.

Your task:
- INTENT and EXPECTED OUTCOME are the only sources of truth.
- You may correct parameter VALUES if and ONLY IF they are EXPLICITLY stated.
- If intent does not specify a value → DO NOT GUESS.

ABSOLUTE RULES (MUST FOLLOW):
- DO NOT change the action type
- DO NOT change control flow
- DO NOT add or remove lines
- DO NOT change locators
- DO NOT change selector strategies
- DO NOT change XPath, CSS, roles, labels, or IDs
- DO NOT rename functions
- DO NOT restructure code
- DO NOT reformat
- DO NOT add comments
- DO NOT remove comments
- DO NOT hallucinate values
- DO NOT normalize values
- DO NOT generalize

You MAY change:
- String literals
- Numbers
- URLs
- Filenames
- Credentials
- Dropdown visible labels
- Input values

ONLY IF explicitly specified in intent or expected outcome.

If no change is needed → return original code.

You must return JSON ONLY.

FORMAT:
{
  "corrected_code": "...",
  "changed": true | false,
  "reason": "explicit technical explanation"
}

INTENT:
{{ intent }}

EXPECTED OUTCOME:
{{ expected or "N/A" }}

REFERENCE CODE:
{{ raw_code }}
""",

        # ============================================================
        # INTENT CORRECTION
        # ============================================================
        "intent_correction": """
Return corrected code ONLY.

You are correcting {{ profile.name }} code to match the intended action.

Rules:
- Return corrected code if needed
- Otherwise return original
- Do NOT add comments
- Do NOT explain
- Preserve style

Intent:
{{ intent }}

Expected outcome:
{{ expected or "N/A" }}

Current code:
{{ code }}
""",
    }

    def __init__(self, template_dir: Optional[Path] = None):
        self._templates = dict(self.BUILT_IN_TEMPLATES)
        self._env = Environment(
            loader=DictLoader(self._templates),
            autoescape=select_autoescape([]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

        self._env.filters["sanitize"] = sanitize_for_prompt

        logger.info(
            "PromptTemplateEngine initialized | templates=%d",
            len(self._templates),
        )

    def render(
        self,
        template_name: str,
        sanitize_inputs: bool = True,
        **kwargs: Any,
    ) -> str:
        try:
            template = self._env.get_template(template_name)
        except TemplateNotFound:
            raise ValueError(f"Template not found: {template_name}")
        
        # Proactively inject active framework profile
        if "profile" not in kwargs:
            from app.core.config import get_settings
            from app.core.framework_profiles import get_framework_profile
            from app.core.context import active_framework_ctx
            
            settings = get_settings()
            framework = active_framework_ctx.get() or settings.AUTOMATION_FRAMEWORK
            profile = get_framework_profile(framework)
            kwargs["profile"] = profile
        
        if sanitize_inputs:
            kwargs = {
                k: sanitize_for_prompt(v) if isinstance(v, str) else v
                for k, v in kwargs.items()
            }
        
        return template.render(**kwargs).strip()

    def list_templates(self) -> list[str]:
        return list(self._templates.keys())

    def add_template(self, name: str, content: str) -> None:
        self._templates[name] = content
        self._env = Environment(
            loader=DictLoader(self._templates),
            autoescape=select_autoescape([]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self._env.filters["sanitize"] = sanitize_for_prompt


_template_engine: Optional[PromptTemplateEngine] = None


def get_template_engine() -> PromptTemplateEngine:
    global _template_engine
    
    if _template_engine is None:
        _template_engine = PromptTemplateEngine()
    
    return _template_engine

