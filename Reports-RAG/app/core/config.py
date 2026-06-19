from functools import lru_cache
import json
from typing import List

from pydantic import AliasChoices, Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_PLACEHOLDER_JWT_SECRET = "replace-this-with-a-long-random-secret"


class Settings(BaseSettings):
    """Centralized application settings."""

    APP_NAME: str = "Reports RAG"
    APP_VERSION: str = "1.0.0"
    AUTHOR: str = "Mokshith Balidi"

    ENV: str = "development"
    DEBUG: bool = False

    HOST: str = "0.0.0.0"
    PORT: int = 8000

    MONGO_ENABLED: bool = True
    MONGODB_URI: str = Field(
        default="",
        validation_alias=AliasChoices("MONGODB_URI", "MONGO_CONNECTION_STRING"),
    )
    MONGODB_DB_NAME: str = "reports_rag"
    MONGODB_BUCKET_NAME: str = "reports"

    API_KEY: str = "change-me-in-production"
    ADMIN_API_KEY: str = "change-me-admin"
    TRUST_FORWARDED_IP: bool = False

    MAX_FILE_SIZE_MB: int = 20

    ENABLE_RATE_LIMITING: bool = True
    RATE_LIMIT_REQUESTS: int = 120
    RATE_LIMIT_WINDOW_SECONDS: int = 60

    ENABLE_TRACING: bool = True
    TRACE_SAMPLE_RATE: float = 0.1
    FAIL_FAST_STARTUP: bool = True

    LOG_LEVEL: str = "INFO"

    CORS_ORIGINS: List[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> List[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]

        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                parsed = json.loads(stripped)
                if not isinstance(parsed, list):
                    raise ValueError("CORS_ORIGINS JSON value must be a list")
                return [str(item).strip() for item in parsed if str(item).strip()]
            return [item.strip() for item in stripped.split(",") if item.strip()]

        raise ValueError("CORS_ORIGINS must be a list or comma-separated string")

    @field_validator("TRACE_SAMPLE_RATE")
    @classmethod
    def validate_trace_sample_rate(cls, value: float) -> float:
        if not 0 <= value <= 1:
            raise ValueError("TRACE_SAMPLE_RATE must be between 0 and 1")
        return value

    @field_validator("MAX_FILE_SIZE_MB")
    @classmethod
    def validate_max_file_size(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("MAX_FILE_SIZE_MB must be greater than 0")
        return value

    @field_validator("API_KEY", mode="before")
    @classmethod
    def normalize_api_key(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @computed_field
    @property
    def VERSION(self) -> str:
        return self.APP_VERSION

    @computed_field
    @property
    def mongo_enabled(self) -> bool:
        return self.MONGO_ENABLED

    @computed_field
    @property
    def is_production(self) -> bool:
        return self.ENV.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> Settings:
    get_settings.cache_clear()
    return get_settings()


settings = get_settings()


def assert_valid_startup_settings(runtime_settings: Settings) -> None:
    errors: list[str] = []

    if runtime_settings.MONGO_ENABLED and not runtime_settings.MONGODB_URI:
        errors.append("MONGODB_URI is required when MONGO_ENABLED=true")

    if runtime_settings.API_KEY == "change-me-in-production":
        errors.append("API_KEY must be configured in production")

    if errors:
        message = "Configuration validation failed:\n" + "\n".join(f"  - {item}" for item in errors)
        raise ValueError(message)
