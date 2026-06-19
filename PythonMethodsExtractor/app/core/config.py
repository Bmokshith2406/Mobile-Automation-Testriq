from functools import cache
from typing import ClassVar

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_DEFAULT_JWT_SECRET = "replace-this-with-a-long-random-secret"


class Settings(BaseSettings):
    # --------------------------------------------------------------
    # Application Metadata
    # --------------------------------------------------------------
    APP_NAME: str = "Playwright Python Method Extractor (AST-Based)"
    VERSION: str = "1.0.0"
    CREATED_BY: str = "MOKSHITH BALIDI"

    # --------------------------------------------------------------
    # MongoDB Configuration
    # --------------------------------------------------------------
    MONGO_URI: str = ""
    MONGO_DB: str = "playwright_python_method_extractor"
    MONGO_REQUIRED_FOR_STARTUP: bool = False

    # --------------------------------------------------------------
    # Collections (constants, not Pydantic fields)
    # --------------------------------------------------------------
    COLLECTION_RAW_SCRIPTS: ClassVar[str] = "raw_scripts"
    COLLECTION_API_LOGS: ClassVar[str] = "api_logs"

    # --------------------------------------------------------------
    # Extraction Settings
    # --------------------------------------------------------------
    MAX_CHARS_PER_CHUNK: int = 20_000
    MAX_SCRIPT_SIZE_BYTES: int = 5 * 1024 * 1024
    IGNORE_METHOD_NAMES: list[str] = []
    INCLUDE_METHOD_NAME_PATTERN: str = ""
    STORE_RAW_SCRIPTS: bool = True

    # --------------------------------------------------------------
    # Logging Configuration
    # --------------------------------------------------------------
    LOG_LEVEL: str = "INFO"
    ENABLE_TRACING: bool = False
    TRACE_SAMPLE_RATE: float = 0.0

    # --------------------------------------------------------------
    # Project Extraction Safety Limits
    # --------------------------------------------------------------
    MAX_ZIP_SIZE_MB: int = 500
    MAX_EXTRACTED_SIZE_MB: int = 2000
    MAX_FILE_COUNT: int = 50_000
    MAX_PY_FILES: int = 10_000

    # --------------------------------------------------------------
    # Security & Auth Settings
    # --------------------------------------------------------------
    API_KEY: str = "change-me-in-production"
    TRUST_FORWARDED_IP: bool = False
    CORS_ALLOWED_ORIGINS: list[str] = ["*"]

    # --------------------------------------------------------------
    # Rate Limiting
    # --------------------------------------------------------------
    RATE_LIMIT_REQUESTS: int = 120
    RATE_LIMIT_WINDOW_SECONDS: int = 60

    # --------------------------------------------------------------
    # Resilience Settings
    # --------------------------------------------------------------
    FAIL_FAST_STARTUP: bool = True

    # --------------------------------------------------------------
    # Pydantic Settings (Pydantic v2)
    # --------------------------------------------------------------
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        enable_decoding=False,
    )

    @field_validator("CORS_ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_cors_allowed_origins(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("IGNORE_METHOD_NAMES", mode="before")
    @classmethod
    def parse_ignore_method_names(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("TRACE_SAMPLE_RATE")
    @classmethod
    def validate_trace_sample_rate(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError("TRACE_SAMPLE_RATE must be between 0 and 1.")
        return value

    @property
    def mongo_enabled(self) -> bool:
        return bool(self.MONGO_URI.strip())


@cache
def get_settings() -> Settings:
    return Settings()


def assert_valid_startup_settings(settings: Settings) -> None:
    errors: list[str] = []

    if settings.API_KEY == "change-me-in-production":
        errors.append("API_KEY must be configured in production.")

    if settings.MONGO_REQUIRED_FOR_STARTUP and not settings.mongo_enabled:
        errors.append("MONGO_URI must be set when MONGO_REQUIRED_FOR_STARTUP is true.")

    if settings.CORS_ALLOWED_ORIGINS == ["*"]:
        errors.append(
            "CORS_ALLOWED_ORIGINS cannot be '*'. "
            "Configure explicit origins for credentialed requests."
        )

    if errors and settings.FAIL_FAST_STARTUP:
        raise ValueError(f"Startup validation failed: {'; '.join(errors)}")
