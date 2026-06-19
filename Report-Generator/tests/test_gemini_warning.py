import sys
import warnings

from pydantic import SecretStr

from app.services.ai.gemini import GeminiProvider, settings


def test_gemini_provider_init_suppresses_known_google_genai_pydantic_warning(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", SecretStr("test-api-key"))

    for module_name in [name for name in list(sys.modules) if name == "google.genai" or name.startswith("google.genai.")]:
        sys.modules.pop(module_name, None)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        provider = GeminiProvider()

    assert provider.model_name == settings.GEMINI_MODEL
    assert not [
        warning
        for warning in caught
        if "<built-in function any> is not a Python type" in str(warning.message)
    ]
