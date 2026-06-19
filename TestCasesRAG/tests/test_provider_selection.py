from unittest.mock import patch

import pytest

from app.core.config import (
    Settings,
    resolve_embedding_model_name,
    resolve_embedding_preset,
    resolve_llm_provider,
    validate_startup_settings,
)
from app.llm.client import LLMClientManager, settings as llm_settings
from app.llm.providers import build_llm_provider
from app.llm.providers.anthropic import AnthropicProvider
from app.llm.providers.chatgpt import ChatGPTProvider
from app.llm.providers.gemini import GeminiProvider
from app.llm.providers.localllm import LocalLLMProvider
from app.services.embedding_backends import get_embedding_backend


@pytest.fixture(autouse=True)
def reset_llm_manager():
    existing = LLMClientManager._instance
    if existing is not None:
        existing.close(wait=False)

    original_values = {
        "LLM_USE_GEMINI": llm_settings.LLM_USE_GEMINI,
        "LLM_USE_OPENAI": llm_settings.LLM_USE_OPENAI,
        "LLM_USE_ANTHROPIC": llm_settings.LLM_USE_ANTHROPIC,
        "LLM_USE_LOCAL": llm_settings.LLM_USE_LOCAL,
        "GOOGLE_API_KEY": llm_settings.GOOGLE_API_KEY,
        "OPENAI_API_KEY": llm_settings.OPENAI_API_KEY,
        "ANTHROPIC_API_KEY": llm_settings.ANTHROPIC_API_KEY,
        "LOCAL_LLM_API_KEY": llm_settings.LOCAL_LLM_API_KEY,
        "OPENAI_MODEL": llm_settings.OPENAI_MODEL,
        "LOCAL_LLM_MODEL": llm_settings.LOCAL_LLM_MODEL,
        "LOCAL_LLM_API_URL": llm_settings.LOCAL_LLM_API_URL,
        "LOCAL_LLM_API_FORMAT": llm_settings.LOCAL_LLM_API_FORMAT,
        "LOCAL_LLM_EXTRA_HEADERS_JSON": llm_settings.LOCAL_LLM_EXTRA_HEADERS_JSON,
        "OPENAI_BASE_URL": llm_settings.OPENAI_BASE_URL,
    }

    yield

    for key, value in original_values.items():
        setattr(llm_settings, key, value)

    existing = LLMClientManager._instance
    if existing is not None:
        existing.close(wait=False)


def test_resolve_provider_and_embedding_preset():
    settings = Settings()
    settings.LLM_USE_GEMINI = False
    settings.LLM_USE_OPENAI = False
    settings.LLM_USE_ANTHROPIC = True
    settings.LLM_USE_LOCAL = False
    settings.EMBEDDING_USE_MINILM_384 = False
    settings.EMBEDDING_USE_MPNET_768 = True
    settings.EMBEDDING_USE_BGE_LARGE_1024 = False

    assert resolve_llm_provider(settings) == "anthropic"
    assert resolve_embedding_preset(settings) == "mpnet_768"
    assert resolve_embedding_model_name(settings) == "sentence-transformers/all-mpnet-base-v2"


def test_individual_provider_files_are_used_for_each_backend():
    settings = Settings()

    settings.LLM_USE_GEMINI = True
    settings.LLM_USE_OPENAI = False
    settings.LLM_USE_ANTHROPIC = False
    settings.LLM_USE_LOCAL = False
    settings.GOOGLE_API_KEY = "gemini-key"
    provider = build_llm_provider(settings)
    assert isinstance(provider, GeminiProvider)

    settings.LLM_USE_GEMINI = False
    settings.LLM_USE_OPENAI = True
    settings.OPENAI_API_KEY = "openai-key"
    provider = build_llm_provider(settings)
    assert isinstance(provider, ChatGPTProvider)

    settings.LLM_USE_OPENAI = False
    settings.LLM_USE_ANTHROPIC = True
    settings.ANTHROPIC_API_KEY = "anthropic-key"
    provider = build_llm_provider(settings)
    assert isinstance(provider, AnthropicProvider)

    settings.LLM_USE_ANTHROPIC = False
    settings.LLM_USE_LOCAL = True
    settings.LOCAL_LLM_API_URL = "http://localhost:11434/v1/chat/completions"
    provider = build_llm_provider(settings)
    assert isinstance(provider, LocalLLMProvider)


def test_individual_embedding_backend_files_are_used_for_each_dimension():
    settings = Settings()

    settings.EMBEDDING_USE_MINILM_384 = True
    settings.EMBEDDING_USE_MPNET_768 = False
    settings.EMBEDDING_USE_BGE_LARGE_1024 = False
    backend = get_embedding_backend(settings)
    assert backend.preset == "minilm_384"
    assert backend.dimensions == 384

    settings.EMBEDDING_USE_MINILM_384 = False
    settings.EMBEDDING_USE_MPNET_768 = True
    backend = get_embedding_backend(settings)
    assert backend.preset == "mpnet_768"
    assert backend.dimensions == 768

    settings.EMBEDDING_USE_MPNET_768 = False
    settings.EMBEDDING_USE_BGE_LARGE_1024 = True
    backend = get_embedding_backend(settings)
    assert backend.preset == "bge_large_1024"
    assert backend.dimensions == 1024


def test_validate_startup_settings_rejects_multiple_provider_switches():
    settings = Settings()
    settings.MONGO_CONNECTION_STRING = "mongodb://example"
    settings.CORS_ALLOWED_ORIGINS = ["http://localhost:3000"]
    settings.GOOGLE_API_KEY = "gemini-key"
    settings.OPENAI_API_KEY = "openai-key"
    settings.LLM_USE_GEMINI = True
    settings.LLM_USE_OPENAI = True
    settings.LLM_USE_ANTHROPIC = False
    settings.LLM_USE_LOCAL = False
    settings.EMBEDDING_USE_MINILM_384 = True
    settings.EMBEDDING_USE_MPNET_768 = True
    settings.EMBEDDING_USE_BGE_LARGE_1024 = False

    errors = validate_startup_settings(settings)

    assert any("Exactly one LLM provider" in error for error in errors)
    assert any("Exactly one embedding preset" in error for error in errors)


def test_llm_client_manager_reloads_when_provider_changes():
    llm_settings.LLM_USE_GEMINI = False
    llm_settings.LLM_USE_OPENAI = True
    llm_settings.LLM_USE_ANTHROPIC = False
    llm_settings.LLM_USE_LOCAL = False
    llm_settings.OPENAI_API_KEY = "openai-key"
    llm_settings.OPENAI_MODEL = "gpt-4o-mini"

    openai_manager = LLMClientManager.get_instance()

    assert openai_manager.provider_name == "openai"
    assert openai_manager.available is True
    assert openai_manager.health()["model"] == "gpt-4o-mini"

    llm_settings.LLM_USE_OPENAI = False
    llm_settings.LLM_USE_LOCAL = True
    llm_settings.LOCAL_LLM_API_URL = "http://localhost:11434/v1/chat/completions"
    llm_settings.LOCAL_LLM_MODEL = "llama3.1"

    local_manager = LLMClientManager.get_instance()

    assert local_manager is not openai_manager
    assert local_manager.provider_name == "local"
    assert local_manager.available is True
    assert local_manager.health()["model"] == "llama3.1"


def test_local_generic_parser_accepts_generated_text_shape():
    llm_settings.LLM_USE_GEMINI = False
    llm_settings.LLM_USE_OPENAI = False
    llm_settings.LLM_USE_ANTHROPIC = False
    llm_settings.LLM_USE_LOCAL = True
    llm_settings.LOCAL_LLM_API_URL = "http://localhost:8080/generate"
    llm_settings.LOCAL_LLM_MODEL = "custom-local"
    llm_settings.LOCAL_LLM_API_FORMAT = "generic"

    provider = build_llm_provider(llm_settings)

    with patch(
        "app.llm.providers.localllm.post_json",
        return_value={"generated_text": "local response"},
    ):
        text = provider.generate_text("hello world")

    assert text == "local response"
