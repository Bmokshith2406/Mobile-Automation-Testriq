# app/core/config.py
"""
Centralized Configuration System

All magic numbers and configurable values are consolidated here.
Environment-driven, cached, and validated.
"""

from functools import lru_cache
from typing import Optional, Literal
from dotenv import load_dotenv

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# --------------------------------------------------
# Safe dotenv loading
# --------------------------------------------------
try:
    load_dotenv()
except OSError:
    pass


class Settings(BaseSettings):
    """
    Central application configuration.
    Environment-driven, cached, validated.
    """

    # -------------------------
    # App metadata
    # -------------------------
    APP_NAME: str = "Test Case Script Generator for Automation Frameworks"
    VERSION: str = "1.0.0"
    CREATED_BY: str = "MOKSHITH BALIDI"
    ENV: Literal["development", "staging", "production"] = Field(default="development")

    # -------------------------
    # Security / API keys
    # -------------------------
    GOOGLE_API_KEY: Optional[str] = Field(
        default=None,
        description="Google Gemini LLM API Key",
    )
    OPENAI_API_KEY: Optional[str] = Field(
        default=None,
        description="OpenAI API Key (fallback provider)",
    )
    ANTHROPIC_API_KEY: Optional[str] = Field(
        default=None,
        description="Anthropic API Key (fallback provider)",
    )

    API_KEY: str = Field(
        default="",
        description=(
            "Shared API key for service authentication. "
            "Must be at least 32 characters. "
            "Generate with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
        ),
    )
    API_KEY_HEADER: str = "X-API-Key"
    API_KEY_ENABLED: bool = True
    TRUST_FORWARDED_IP: bool = False

    # -------------------------
    # LLM Configuration
    # -------------------------
    LLM_PROVIDER: Literal["gemini", "openai"] = Field(
        default="gemini",
        description=(
            "Primary LLM provider. Valid values: 'gemini', 'openai'. "
            "Note: 'anthropic' is declared in the codebase but not yet implemented."
        ),
    )
    PRIMARY_MODEL: str = Field(
        default="gemini-2.5-pro",
        validation_alias=AliasChoices("PRIMARY_MODEL", "LLM_MODEL", "LLM_MODEL_NAME"),
        description="Default LLM model name",
    )
    FALLBACK_MODEL: str = Field(
        default="gemini-2.5-flash",
        validation_alias=AliasChoices("FALLBACK_MODEL", "LLM_FALLBACK_MODEL"),
        description="Fallback model for degraded operation",
    )
    MAX_CONCURRENT_LLM_CALLS: int = Field(
        default=8,
        ge=1,
        le=10,
        description="Maximum concurrent LLM requests",
    )
    MAX_OUTPUT_TOKENS: int = Field(
        default=2048,
        ge=256,
        le=8192,
        description="Maximum output tokens per LLM call",
    )
    LLM_TIMEOUT_SECONDS: int = Field(
        default=60,
        ge=10,
        le=300,
        description="Timeout for LLM API calls",
    )
    LLM_DEFAULT_RETRIES: int = Field(
        default=2,
        ge=0,
        le=5,
        description="Number of retries for failed LLM calls",
    )
    LLM_RATE_LIMIT_SLEEP: float = Field(
        default=2.0,
        ge=0.5,
        le=30.0,
        description="Sleep duration between retries",
    )
    LLM_TEMPERATURE: float = Field(
        default=0.1,
        ge=0.0,
        le=2.0,
        description="LLM temperature setting",
    )
    LLM_TOP_P: float = Field(
        default=0.95,
        ge=0.0,
        le=1.0,
        description="LLM top_p setting",
    )

    # -------------------------
    # Confidence & Validation
    # -------------------------
    MIN_CONFIDENCE_THRESHOLD: int = Field(
        default=80,
        ge=0,
        le=100,
        description="Minimum confidence for LLM extractions",
    )
    MAX_EXTRACTOR_RETRIES: int = Field(
        default=2,
        ge=0,
        le=5,
        description="Max retries for low confidence extractions",
    )
    MAX_VERIFIER_REPAIR_ATTEMPTS: int = Field(
        default=4,
        ge=1,
        le=10,
        description="Max attempts for step verification repairs",
    )

    # -------------------------
    # Script Generation / LLM Prompts
    # -------------------------
    AUTOMATION_FRAMEWORK: Literal["playwright", "selenium", "cypress", "appium"] = Field(
        default="playwright",
        description="Target framework for generated test code",
    )
    GENERATION_TIMEOUT_SECONDS: int = Field(
        default=300,
        ge=30,
        le=1200,
        description="Max seconds for a single script generation request",
    )
    STREAM_MAX_CONCURRENT: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum concurrent SSE streaming requests",
    )
    INTENT_CORRECTION_ENABLED: bool = Field(
        default=True,
        description="Enable LLM-based intent correction for matched scripts",
    )
    EXPECT_TIMEOUT_MS: int = Field(
        default=5000,
        ge=1000,
        le=60000,
        description="Default timeout for framework expects/assertions",
    )
    DEFAULT_STEP_RETRIES: int = Field(
        default=1,
        ge=0,
        le=5,
        description="Default step retry count",
    )
    ACTION_TIMEOUT_MS: int = Field(
        default=30000,
        ge=5000,
        le=120000,
        description="Default timeout for framework actions",
    )

    # -------------------------
    # Runtime limits
    # -------------------------
    MAX_REQUEST_SIZE_BYTES: int = Field(
        default=1_000_000,
        ge=10_000,
        le=10_000_000,
        description="Maximum request body size",
    )
    MAX_JSON_CHARS: int = Field(
        default=25000,
        ge=1000,
        le=200000,
        description="Maximum JSON extraction size",
    )
    MAX_SCRIPT_SIZE_BYTES: int = Field(
        default=500_000,
        ge=10_000,
        le=5_000_000,
        description="Maximum generated script size",
    )

    # -------------------------
    # -------------------------
    BATCH_MAX_ITEMS: int = Field(
        default=50,
        ge=1,
        le=100,
        description="Maximum items per batch request",
    )
    BATCH_MAX_PARALLEL: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Maximum parallel workers for batch",
    )

    # -------------------------
    # Rate Limiting
    # -------------------------
    RATE_LIMIT_ENABLED: bool = Field(
        default=True,
        description="Enable API rate limiting",
    )
    RATE_LIMIT_REQUESTS: int = Field(
        default=10,
        ge=1,
        le=1000,
        description="Max requests per time window",
    )
    RATE_LIMIT_WINDOW_SECONDS: int = Field(
        default=60,
        ge=1,
        le=3600,
        description="Rate limit time window in seconds",
    )

    # -------------------------
    # Caching
    # -------------------------
    CACHE_ENABLED: bool = Field(
        default=True,
        description="Enable LLM response caching",
    )
    CACHE_TTL_SECONDS: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description="Cache entry TTL in seconds",
    )
    REDIS_URL: Optional[str] = Field(
        default=None,
        description="Redis URL for caching (optional)",
    )

    # -------------------------
    # Circuit Breaker
    # -------------------------
    CIRCUIT_BREAKER_ENABLED: bool = Field(
        default=True,
        description="Enable circuit breaker for LLM calls",
    )
    CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Failures before circuit opens",
    )
    CIRCUIT_BREAKER_RECOVERY_TIMEOUT: int = Field(
        default=30,
        ge=5,
        le=300,
        description="Seconds before attempting recovery",
    )

    # -------------------------
    # Webhooks
    # -------------------------
    WEBHOOK_TIMEOUT_SECONDS: int = Field(
        default=10,
        ge=1,
        le=60,
        description="Timeout for webhook notifications",
    )
    WEBHOOK_MAX_RETRIES: int = Field(
        default=3,
        ge=0,
        le=5,
        description="Max webhook delivery retries",
    )
    WEBHOOK_SECRET: Optional[str] = Field(
        default=None,
        description=(
            "Shared secret for HMAC-SHA256 signing of outgoing webhook payloads. "
            "Receivers can verify the X-Webhook-Signature header with this value. "
            "Leave unset to skip signing."
        ),
    )

    # -------------------------
    # File Cleanup
    # -------------------------
    CLEANUP_ENABLED: bool = Field(
        default=True,
        description="Enable periodic cleanup of generated files",
    )
    CLEANUP_MAX_AGE_HOURS: int = Field(
        default=24,
        ge=1,
        le=168,
        description="Max age of generated files before cleanup",
    )

    # -------------------------
    # CORS
    # -------------------------
    CORS_ORIGINS: list[str] = Field(
        default=[],
        description=(
            "Allowed CORS origins. Never use ['*'] in production. "
            "Example: ['https://yourfrontend.com']. "
            "Defaults to empty (no cross-origin access) — must be set explicitly."
        ),
    )

    # -------------------------
    # Observability
    # -------------------------
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        description="Application log level",
    )
    LOG_FORMAT: Literal["text", "json"] = Field(
        default="text",
        description="Log output format: 'text' for human-readable, 'json' for structured",
    )
    LOG_TO_FILE: bool = Field(
        default=False,
        description="Write application logs to logs/app.log in addition to stdout",
    )
    TRACING_ENABLED: bool = Field(
        default=False,
        description="Enable OpenTelemetry tracing",
    )
    TRACING_ENDPOINT: Optional[str] = Field(
        default=None,
        description="OpenTelemetry collector endpoint",
    )
    METRICS_ENABLED: bool = Field(
        default=True,
        description="Enable metrics collection",
    )

    # --------------------------------------------------
    # Validators
    # --------------------------------------------------
    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            stripped = v.strip()
            if stripped.startswith("["):
                import json as _json
                try:
                    parsed = _json.loads(stripped)
                    if isinstance(parsed, list):
                        return [str(o).strip() for o in parsed if str(o).strip()]
                except _json.JSONDecodeError:
                    pass
            return [origin.strip() for origin in stripped.split(",") if origin.strip()]
        return v

    @model_validator(mode="after")
    def validate_production_secrets(self):
        # --- API_KEY strength check (all environments) ---
        if self.API_KEY_ENABLED:
            _known_weak_keys = {
                "",
                "super-secret-key",
                "your_super_secure_api_key_here",
                "AutomationScriptGenerator",
                "changeme",
                "test",
                "password",
                "secret",
                "apikey",
            }
            if self.API_KEY in _known_weak_keys:
                raise ValueError(
                    "API_KEY is empty or a known placeholder. "
                    "Generate one with: "
                    "python -c \"import secrets; print(secrets.token_urlsafe(32))\""
                )
            if len(self.API_KEY) < 32:
                raise ValueError(
                    f"API_KEY must be at least 32 characters long "
                    f"(current: {len(self.API_KEY)} chars). "
                    "Generate one with: "
                    "python -c \"import secrets; print(secrets.token_urlsafe(32))\""
                )

        # --- CORS wildcard guard (production only) ---
        if self.ENV == "production" and "*" in self.CORS_ORIGINS:
            raise ValueError(
                "CORS_ORIGINS cannot contain '*' in production. "
                "Set explicit origins, e.g.: CORS_ORIGINS=https://yourfrontend.com"
            )

        return self

    # --------------------------------------------------
    # Pydantic v2 settings config
    # --------------------------------------------------
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """
    Cached settings accessor.
    Ensures environment is read only once.
    """
    return Settings()

