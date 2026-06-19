import logging
from app.core.config import get_settings
from app.services.generators.base_generator import BaseGenerator

logger = logging.getLogger("generator_factory")


def get_generator(target_framework: str | None = None) -> BaseGenerator:
    """
    Factory function to retrieve the active test code generator engine.
    """
    settings = get_settings()
    framework = (target_framework or settings.AUTOMATION_FRAMEWORK).lower().strip()

    logger.info("Resolving generator for framework: %s", framework)

    if framework == "playwright":
        from app.services.generators.playwright_generator import PlaywrightPythonGenerator
        return PlaywrightPythonGenerator()
    elif framework == "selenium":
        from app.services.generators.selenium_generator import SeleniumGenerator
        return SeleniumGenerator()
    elif framework == "cypress":
        from app.services.generators.cypress_generator import CypressGenerator
        return CypressGenerator()
    elif framework == "appium":
        from app.services.generators.appium_generator import AppiumGenerator
        return AppiumGenerator()
    else:
        raise ValueError(f"Unsupported automation framework: {settings.AUTOMATION_FRAMEWORK}")

