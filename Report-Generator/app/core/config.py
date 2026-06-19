from functools import lru_cache
from typing import List, Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Enterprise application configuration."""

    # ------------------------------------------------------------------
    # Environment
    # ------------------------------------------------------------------
    ENVIRONMENT: Literal["dev", "staging", "prod"] = "dev"
    DEBUG: bool = False

    # ------------------------------------------------------------------
    # Service
    # ------------------------------------------------------------------
    SERVICE_NAME: str = "Artifact Report Generator"
    SERVICE_VERSION: str = "1.0.0"
    CREATED_BY: str = "Mokshith Balidi"

    # ------------------------------------------------------------------
    # Server
    # ------------------------------------------------------------------
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WORKERS: int = 1

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------
    API_PREFIX: str = "/api/v1"

    # ------------------------------------------------------------------
    # AI
    # ------------------------------------------------------------------
    LLM_PROVIDER: Literal["gemini", "openai", "anthropic"] = "gemini"
    GEMINI_API_KEY: SecretStr | None = None
    GEMINI_MODEL: str = "gemini-2.0-flash"
    LLM_MODEL_NAME: str | None = None
    LLM_FALLBACK_MODEL: str = "gemini-2.5-flash"
    OPENAI_API_KEY: SecretStr | None = None
    OPENAI_MODEL: str = "gpt-4o"
    ANTHROPIC_API_KEY: SecretStr | None = None
    ANTHROPIC_MODEL: str = "claude-3-7-sonnet-20250219"
    AI_ENABLED: bool = True
    AI_MAX_RETRIES: int = 3
    AI_TIMEOUT_SECONDS: int = 30
    AI_MAX_CONCURRENCY: int = 5
    AI_OVERALL_TIMEOUT_SECONDS: int = 45

    # ------------------------------------------------------------------
    # Rate Limiting
    # ------------------------------------------------------------------
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_PER_MINUTE: int = 30
    RATE_LIMIT_BACKEND: Literal["memory", "redis"] = "memory"
    REDIS_URL: SecretStr | None = None

    # ------------------------------------------------------------------
    # File Upload
    # ------------------------------------------------------------------
    MAX_ZIP_SIZE_MB: int = 500
    UPLOAD_TIMEOUT_SECONDS: int = 300
    MAX_ZIP_ENTRIES: int = 2000
    MAX_DECOMPRESSED_SIZE_MB: int = 1024
    MAX_COMPRESSION_RATIO: float = 100.0
    MAX_STEP_COUNT: int = 500
    MAX_SCREENSHOT_SIZE_MB: int = 15
    MAX_VIDEO_SIZE_MB: int = 250
    MAX_SCRIPT_SIZE_KB: int = 1024

    # ------------------------------------------------------------------
    # Error Tracking
    # ------------------------------------------------------------------
    SENTRY_DSN: SecretStr | None = None
    SENTRY_TRACES_SAMPLE_RATE: float = 1.0
    SENTRY_PROFILES_SAMPLE_RATE: float = 1.0

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # ------------------------------------------------------------------
    # CORS / Security
    # ------------------------------------------------------------------
    CORS_ORIGINS: List[str] = ["*"]
    TRUSTED_HOSTS: List[str] = []
    TRUST_FORWARDED_IP: bool = False
    
    # ------------------------------------------------------------------
    # API KEY / Security
    # ------------------------------------------------------------------
    
    API_KEY_ENABLED: bool = True
    API_KEY: SecretStr | None = None
    API_KEY_HEADER: str = "X-API-Key"

    # ------------------------------------------------------------------
    # Computed
    # ------------------------------------------------------------------
    @property
    def MAX_ZIP_SIZE_BYTES(self) -> int:
        return self.MAX_ZIP_SIZE_MB * 1024 * 1024

    @property
    def MAX_DECOMPRESSED_SIZE_BYTES(self) -> int:
        return self.MAX_DECOMPRESSED_SIZE_MB * 1024 * 1024

    @property
    def MAX_SCREENSHOT_SIZE_BYTES(self) -> int:
        return self.MAX_SCREENSHOT_SIZE_MB * 1024 * 1024

    @property
    def MAX_VIDEO_SIZE_BYTES(self) -> int:
        return self.MAX_VIDEO_SIZE_MB * 1024 * 1024

    @property
    def MAX_SCRIPT_SIZE_BYTES(self) -> int:
        return self.MAX_SCRIPT_SIZE_KB * 1024

    @property
    def SENTRY_ENABLED(self) -> bool:
        return bool(self.SENTRY_DSN and self.SENTRY_DSN.get_secret_value().strip())

    @property
    def REDIS_ENABLED(self) -> bool:
        return bool(self.REDIS_URL and self.REDIS_URL.get_secret_value().strip())

    @property
    def IS_PRODUCTION(self) -> bool:
        return self.ENVIRONMENT == "prod"

    @property
    def TRACES_SAMPLE_RATE(self) -> float:
        if self.ENVIRONMENT == "prod":
            return 0.1
        if self.ENVIRONMENT == "staging":
            return 0.5
        return self.SENTRY_TRACES_SAMPLE_RATE

    @property
    def PROFILES_SAMPLE_RATE(self) -> float:
        if self.ENVIRONMENT == "prod":
            return 0.1
        if self.ENVIRONMENT == "staging":
            return 0.5
        return self.SENTRY_PROFILES_SAMPLE_RATE

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------
    @field_validator("PORT")
    def validate_port(cls, v):
        if not (1 <= v <= 65535):
            raise ValueError("PORT must be between 1 and 65535")
        return v

    @field_validator("WORKERS")
    def validate_workers(cls, v):
        if v < 1:
            raise ValueError("WORKERS must be >= 1")
        return v

    @field_validator("RATE_LIMIT_PER_MINUTE")
    def validate_rate_limit(cls, v):
        if v < 1:
            raise ValueError("RATE_LIMIT_PER_MINUTE must be >= 1")
        return v

    @field_validator("AI_MAX_RETRIES", "AI_TIMEOUT_SECONDS", "AI_MAX_CONCURRENCY", "AI_OVERALL_TIMEOUT_SECONDS")
    def validate_ai_settings(cls, v):
        if v < 1:
            raise ValueError("AI limits and timeouts must be >= 1")
        return v

    @field_validator("MAX_ZIP_SIZE_MB")
    def validate_zip_size(cls, v):
        if v < 1:
            raise ValueError("MAX_ZIP_SIZE_MB must be >= 1")
        return v

    @field_validator(
        "MAX_ZIP_ENTRIES",
        "MAX_DECOMPRESSED_SIZE_MB",
        "MAX_STEP_COUNT",
        "MAX_SCREENSHOT_SIZE_MB",
        "MAX_VIDEO_SIZE_MB",
        "MAX_SCRIPT_SIZE_KB",
    )
    def validate_archive_limits(cls, v):
        if v < 1:
            raise ValueError("Archive limits must be >= 1")
        return v

    @field_validator("MAX_COMPRESSION_RATIO")
    def validate_compression_ratio(cls, v):
        if v <= 1:
            raise ValueError("MAX_COMPRESSION_RATIO must be > 1")
        return v

    @model_validator(mode="after")
    def resolve_gemini_model(self) -> "Settings":
        if self.LLM_MODEL_NAME:
            self.GEMINI_MODEL = self.LLM_MODEL_NAME
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()
