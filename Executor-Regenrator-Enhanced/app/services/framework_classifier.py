import re
from pathlib import Path
from typing import Optional
from app.core.llm_executor import LLMExecutor

class FrameworkClassifier:
    """
    Agent service inside Executor-Regenerator to identify the active framework.
    Uses fast regex heuristics first, falling back to LLM classification when ambiguous.
    """

    def __init__(self):
        self._llm = None

    @property
    def llm(self) -> LLMExecutor:
        if self._llm is None:
            self._llm = LLMExecutor.get_instance()
        return self._llm

    async def classify_framework(self, script_path: str) -> str:
        try:
            code = Path(script_path).read_text(encoding="utf-8")
        except Exception:
            return "playwright"

        code_lower = code.lower()
        
        # Fast heuristics. Appium scripts often import webdriver too, so Appium
        # must win before the broader Selenium/WebDriver check.
        has_appium = (
            "from appium" in code_lower
            or "import appium" in code_lower
            or "appium.webdriver" in code_lower
            or "appiumby" in code_lower
        )
        if has_appium:
            return "appium"

        has_playwright = "playwright" in code_lower
        has_selenium = "selenium" in code_lower or "webdriver" in code_lower
        has_cypress = "cypress" in code_lower

        active_heuristics = [
            ("playwright", has_playwright),
            ("selenium", has_selenium),
            ("appium", has_appium),
            ("cypress", has_cypress),
        ]
        detected = [name for name, active in active_heuristics if active]

        # If exactly one is detected, return it immediately (saves LLM tokens & time)
        if len(detected) == 1:
            return detected[0]

        # LLM Classification fallback for ambiguous scripts
        prompt = (
            "Analyze the following automated test code and identify the testing framework used (e.g., playwright, selenium, appium, cypress).\n"
            "Return exactly one word (the name of the framework) in lower case. If you cannot identify it, return 'playwright'.\n\n"
            f"Code:\n{code[:3000]}"
        )

        try:
            res = await self.llm.run_classifier(prompt)
            if res:
                framework = res.strip().lower()
                if framework in {"playwright", "selenium", "appium", "cypress"}:
                    return framework
        except Exception:
            pass
        
        return "playwright"
