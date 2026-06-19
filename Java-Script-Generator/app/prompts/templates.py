# app/prompts/templates.py
"""
Prompt Template Convenience Class

Provides typed access to common prompt templates.
"""

from typing import Optional

from app.prompts.template_engine import get_template_engine


class PromptTemplates:
    """
    Convenience class for accessing prompt templates.
    
    Provides type-safe methods for rendering common prompts.
    """
    
    @staticmethod
    def classification(
        intent: str,
        expected: Optional[str] = None,
        script: Optional[str] = None,
    ) -> str:
        """Render classification prompt."""
        return get_template_engine().render(
            "classification",
            intent=intent,
            expected=expected,
            script=script,
        )
    
    @staticmethod
    def click_locator(
        intent: str,
        script: Optional[str] = None,
    ) -> str:
        """Render click locator extraction prompt."""
        return get_template_engine().render(
            "click_locator",
            intent=intent,
            script=script,
        )
    
    @staticmethod
    def type_locator(
        intent: str,
        script: Optional[str] = None,
    ) -> str:
        """Render type locator extraction prompt."""
        return get_template_engine().render(
            "type_locator",
            intent=intent,
            script=script,
        )
    
    @staticmethod
    def type_value(
        intent: str,
        script: Optional[str] = None,
    ) -> str:
        """Render type value extraction prompt."""
        return get_template_engine().render(
            "type_value",
            intent=intent,
            script=script,
        )
    
    @staticmethod
    def select_locator(
        intent: str,
        script: Optional[str] = None,
    ) -> str:
        """Render select locator extraction prompt."""
        return get_template_engine().render(
            "select_locator",
            intent=intent,
            script=script,
        )
    
    @staticmethod
    def select_value(
        intent: str,
        script: Optional[str] = None,
    ) -> str:
        """Render select value extraction prompt."""
        return get_template_engine().render(
            "select_value",
            intent=intent,
            script=script,
        )
    
    @staticmethod
    def assert_extraction(
        intent: str,
        expected: Optional[str] = None,
        script: Optional[str] = None,
    ) -> str:
        """Render assertion extraction prompt."""
        return get_template_engine().render(
            "assert_extraction",
            intent=intent,
            expected=expected,
            script=script,
        )
    
    @staticmethod
    def step_decomposition(
        intent: str,
        expected: Optional[str] = None,
        script: Optional[str] = None,
    ) -> str:
        """Render step decomposition prompt."""
        return get_template_engine().render(
            "step_decomposition",
            intent=intent,
            expected=expected,
            script=script,
        )
    
    @staticmethod
    def intent_correction(
        intent: str,
        code: str,
        expected: Optional[str] = None,
    ) -> str:
        """Render intent correction prompt."""
        return get_template_engine().render(
            "intent_correction",
            intent=intent,
            code=code,
            expected=expected,
        )

    @staticmethod
    def intent_parameter_correction(
        intent: str,
        raw_code: str,
        expected: Optional[str] = None,
    ) -> str:
        """Render CIR-safe parameter correction prompt."""
        return get_template_engine().render(
            "intent_parameter_correction",
            intent=intent,
            raw_code=raw_code,
            expected=expected,
        )

    @staticmethod
    def playwright_role_upgrade(raw_code: str) -> str:
        """Render safe Playwright role-upgrade prompt."""
        return get_template_engine().render(
            "playwright_role_upgrade",
            raw_code=raw_code,
        )

    @staticmethod
    def step_verification(
        intent: str,
        generated_code: str,
        matched_script: Optional[str] = None,
    ) -> str:
        """Render Playwright step verification prompt."""
        return get_template_engine().render(
            "step_verification",
            intent=intent,
            generated_code=generated_code,
            matched_script=matched_script,
        )

    @staticmethod
    def step_safety_repair(
        intent: str,
        original_code: str,
        reason: Optional[str] = None,
    ) -> str:
        """Render safety-only step repair prompt."""
        return get_template_engine().render(
            "step_safety_repair",
            intent=intent,
            original_code=original_code,
            reason=reason,
        )

