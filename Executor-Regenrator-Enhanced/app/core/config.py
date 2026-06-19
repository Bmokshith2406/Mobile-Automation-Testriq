"""
Enhanced Configuration Module - Production Grade

Features:
- Environment-specific configurations (development, staging, production)
- Feature flags for gradual rollouts
- API key rotation support
- Comprehensive validation
- Observability configuration
"""

from functools import lru_cache
from types import SimpleNamespace
from typing import Literal, Optional, List
from dotenv import load_dotenv

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# --------------------------------------------------
# Safe dotenv loading
# --------------------------------------------------
try:
    load_dotenv()
except Exception:
    pass


class Settings(BaseSettings):
    """
    Central application configuration with production-grade features.

    This application performs STEP-LEVEL automation repair,
    not end-to-end test generation.
    """

    # -------------------------
    # App metadata
    # -------------------------
    APP_NAME: str = "Multi-Framework Step Repair Engine"
    VERSION: str = "3.0.0"
    CREATED_BY: str = "MOKSHITH BALIDI"
    ENV: Literal["development", "staging", "production"] = Field(
        default="development",
        description="Runtime environment"
    )

    # -------------------------
    # Security / API keys
    # -------------------------
    GOOGLE_API_KEY: Optional[str] = Field(
        default=None,
        description="Primary Google Gemini LLM API Key",
    )
    
    # Multiple API keys for rotation
    GOOGLE_API_KEYS: List[str] = Field(
        default_factory=list,
        description="List of Google API keys for rotation"
    )
    
    # API Authentication
    API_SECRET_KEY: Optional[str] = Field(
        default=None,
        description="Secret key for API authentication"
    )
    
    API_KEY_HEADER: str = Field(
        default="X-API-Key",
        description="Header name for API key"
    )
    
    # Allowed API keys for multi-tenant access
    ALLOWED_API_KEYS: List[str] = Field(
        default_factory=list,
        description="List of allowed API keys for authentication"
    )

    TRUST_FORWARDED_IP: bool = False

    # -------------------------
    # Runtime limits
    # -------------------------
    MAX_REQUEST_SIZE_BYTES: int = Field(
        default=5_000_000,
        ge=1_000,
        le=50_000_000,
        description="Maximum request body size in bytes"
    )

    # Step regeneration safety limits
    MAX_LLM_MODIFICATIONS: int = Field(default=1, ge=1, le=5)
    MAX_VERIFICATION_PASSES: int = Field(default=2, ge=1, le=5)
    MAX_STEP_CODE_LENGTH: int = Field(default=2_000, ge=100, le=10_000)
    MAX_STEP_LINES: int = Field(default=50, ge=10, le=200)

    # -------------------------
    # LLM Configuration
    # -------------------------
    LLM_TIMEOUT_SECONDS: int = Field(default=150, ge=10, le=300)
    LLM_MAX_RETRIES: int = Field(default=3, ge=0, le=10)
    LLM_MAX_CONCURRENT_CALLS: int = Field(default=3, ge=1, le=20)
    LLM_MODEL_NAME: str = Field(default="gemini-2.5-pro", description="Primary Google Gemini model")
    LLM_FALLBACK_MODEL: str = Field(default="gemini-2.5-flash", description="Fallback Google Gemini model")
    LLM_RATE_LIMIT_SLEEP: float = Field(default=2.0, ge=0.5, le=30.0)
    
    # Token limits
    LLM_VERIFIER_MAX_TOKENS: int = Field(default=512, ge=128, le=8192)
    LLM_CLASSIFIER_MAX_TOKENS: int = Field(default=512, ge=128, le=8192)
    LLM_EXTRACTOR_MAX_TOKENS: int = Field(default=8192, ge=1024, le=16384)
    LLM_MODIFIER_MAX_TOKENS: int = Field(default=8192, ge=2048, le=16384)

    # -------------------------
    # Artifact constraints
    # -------------------------
    MAX_SCREENSHOT_SIZE_BYTES: int = Field(default=10_000_000, ge=1_000_000)
    ALLOWED_SCREENSHOT_MIME_TYPES: List[str] = Field(
        default=["image/png", "image/jpeg", "image/webp"]
    )

    # -------------------------
    # CORS
    # -------------------------
    CORS_ORIGINS: List[str] = Field(
        default=["http://localhost:3000"],
        description="Allowed CORS origins"
    )
    CORS_ALLOW_CREDENTIALS: bool = Field(default=False)
    CORS_ALLOW_METHODS: List[str] = Field(default=["POST", "GET", "OPTIONS"])
    CORS_ALLOW_HEADERS: List[str] = Field(
        default=["Authorization", "Content-Type", "X-API-Key", "X-Request-ID"]
    )

    # -------------------------
    # Rate Limiting
    # -------------------------
    RATE_LIMIT_ENABLED: bool = Field(default=True)
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = Field(default=60, ge=1, le=1000)
    RATE_LIMIT_REQUESTS_PER_HOUR: int = Field(default=1000, ge=1, le=10000)
    RATE_LIMIT_BURST_SIZE: int = Field(default=10, ge=1, le=100)

    # -------------------------
    # Feature Flags
    # -------------------------
    ENABLE_MULTIMODAL: bool = Field(
        default=True,
        description="Enable multimodal (image) LLM analysis"
    )
    ENABLE_SELF_HEALING: bool = Field(
        default=True,
        description="Enable self-healing execution"
    )
    ENABLE_API_AUTH: bool = Field(
        default=True,
        description="Enable API key authentication"
    )
    ENABLE_RATE_LIMITING: bool = Field(
        default=True,
        description="Enable rate limiting"
    )
    ENABLE_METRICS: bool = Field(
        default=True,
        description="Enable Prometheus metrics"
    )
    ENABLE_TRACING: bool = Field(
        default=False,
        description="Enable OpenTelemetry tracing"
    )
    DRY_RUN_MODE: bool = Field(
        default=False,
        description="Dry run mode - no actual repairs"
    )
    ENABLE_SANDBOX_EXECUTION: bool = Field(
        default=True,
        description="Enable sandboxed Python execution"
    )
    SANDBOX_ENABLED: bool = Field(
        default=True,
        description="Enable python script execution sandboxing"
    )
    SANDBOX_USE_DOCKER: bool = Field(
        default=False,
        description="Use docker for python execution sandboxing"
    )
    SANDBOX_ALLOW_NETWORK: bool = Field(
        default=False,
        description="Allow network in docker sandbox"
    )
    SANDBOX_DOCKER_IMAGE: str = Field(
        default="python:3.11-slim",
        description="Docker image to use for python sandbox"
    )
    ALLOW_UNSAFE_HOST_EXECUTION_IN_PRODUCTION: bool = Field(
        default=False,
        description="Allow host subprocess execution in production when Docker sandboxing is unavailable"
    )

    # -------------------------
    # Observability
    # -------------------------
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO"
    )
    LOG_FORMAT: str = Field(
        default="%(asctime)s | %(name)s | %(levelname)s | %(message)s | %(extras)s"
    )
    LOG_FORMAT_MODE: Literal["JSON", "CONSOLE", "PRETTY"] = Field(
        default="CONSOLE",
        description="Log formatting mode (JSON for structured logs, CONSOLE for human-readable logs, PRETTY for simplified/colorized logs)"
    )
    
    # Metrics
    METRICS_PORT: int = Field(default=9090, ge=1024, le=65535)
    METRICS_PATH: str = Field(default="/metrics")
    
    # Tracing
    OTEL_EXPORTER_ENDPOINT: Optional[str] = Field(
        default=None,
        description="OpenTelemetry exporter endpoint"
    )
    OTEL_SERVICE_NAME: str = Field(default="playwright-repair-engine")
    
    # Sentry
    SENTRY_DSN: Optional[str] = Field(
        default=None,
        description="Sentry DSN for error tracking"
    )
    SENTRY_ENVIRONMENT: Optional[str] = Field(default=None)
    SENTRY_TRACES_SAMPLE_RATE: float = Field(default=0.1, ge=0.0, le=1.0)

    # -------------------------
    # Database (MongoDB persistence)
    # -------------------------
    MONGODB_URL: Optional[str] = Field(
        default=None,
        description="MongoDB connection URL"
    )
    MONGODB_DB_NAME: str = Field(
        default="repair_engine",
        description="MongoDB database name"
    )
    DATABASE_ECHO: bool = Field(default=False)
    ALLOW_INMEMORY_DATABASE_FALLBACK: bool = Field(
        default=False,
        description="Allow falling back to the in-memory repository when MongoDB is configured but unavailable"
    )


    # -------------------------
    # Redis (for caching/state)
    # -------------------------
    REDIS_URL: Optional[str] = Field(
        default=None,
        description="Redis connection URL"
    )
    REDIS_MAX_CONNECTIONS: int = Field(default=10, ge=1, le=100)
    REDIS_KEY_PREFIX: str = Field(default="repair:")
    REPAIR_PIPELINE_TIMEOUT_SECONDS: int = 120

    # -------------------------
    # Task Queue (Celery)
    # -------------------------
    CELERY_BROKER_URL: Optional[str] = Field(
        default=None,
        description="Celery broker URL"
    )
    CELERY_RESULT_BACKEND: Optional[str] = Field(
        default=None,
        description="Celery result backend URL"
    )
    CELERY_TASK_TIMEOUT: int = Field(default=300, ge=60, le=3600)
    CELERY_TASK_SOFT_TIMEOUT: int = Field(default=270, ge=30, le=3600)
    CELERY_WORKER_PREFETCH_MULTIPLIER: int = Field(default=1, ge=1, le=100)
    CELERY_WORKER_CONCURRENCY: int = Field(default=4, ge=1, le=100)

    # -------------------------
    # Executor Configuration
    # -------------------------
    EXECUTOR_TIMEOUT_SECONDS: int = Field(default=800, ge=30, le=3600)
    EXECUTOR_BASE_WORK_DIR: Optional[str] = Field(default=None)

    # -------------------------
    # Appium Configuration
    # -------------------------
    ENABLE_APPIUM_EXECUTION: bool = Field(
        default=True,
        description="Enable Appium-generated Python script execution support",
    )
    APPIUM_SERVER_URL: str = Field(
        default="http://YOUR_APPIUM_VM_IP:4723/wd/hub",
        description="Remote Appium server URL used by generated Appium scripts",
    )
    APPIUM_DEVICE_MATRIX_JSON: Optional[str] = Field(
        default=None,
        description="Optional default Appium runtime device matrix JSON",
    )
    APPIUM_DEVICE_MATRIX_PATH: str = Field(
        default="appium_device_matrix.json",
        description=(
            "Path to the default Appium runtime device matrix JSON file. "
            "Resolved relative to the Executor-Regenerator project root when not absolute."
        ),
    )
    
    # -------------------------
    # Circuit Breaker
    # -------------------------
    CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = Field(default=5, ge=1, le=50)
    CIRCUIT_BREAKER_RESET_TIMEOUT: int = Field(default=60, ge=10, le=600)

    # --------------------------------------------------
    # Computed Properties
    # --------------------------------------------------
    
    @property
    def is_production(self) -> bool:
        return self.ENV == "production"
    
    @property
    def is_development(self) -> bool:
        return self.ENV == "development"
    
    @property
    def is_staging(self) -> bool:
        return self.ENV == "staging"
    
    @property
    def effective_api_keys(self) -> List[str]:
        """Get all available API keys for rotation."""
        keys = list(self.GOOGLE_API_KEYS)
        if self.GOOGLE_API_KEY and self.GOOGLE_API_KEY not in keys:
            keys.insert(0, self.GOOGLE_API_KEY)
        return keys

    @property
    def redis(self):
        """Compatibility view for legacy modules that expect nested Redis settings."""
        return SimpleNamespace(
            enabled=bool(self.REDIS_URL),
            url=self.REDIS_URL,
            max_connections=self.REDIS_MAX_CONNECTIONS,
            key_prefix=self.REDIS_KEY_PREFIX,
        )

    @property
    def celery(self):
        """Compatibility view for legacy modules that expect nested Celery settings."""
        return SimpleNamespace(
            broker_url=self.CELERY_BROKER_URL,
            result_backend=self.CELERY_RESULT_BACKEND,
            task_time_limit=self.CELERY_TASK_TIMEOUT,
            task_soft_time_limit=min(
                self.CELERY_TASK_SOFT_TIMEOUT,
                self.CELERY_TASK_TIMEOUT,
            ),
            worker_prefetch_multiplier=self.CELERY_WORKER_PREFETCH_MULTIPLIER,
            worker_concurrency=self.CELERY_WORKER_CONCURRENCY,
        )

    # --------------------------------------------------
    # Validators
    # --------------------------------------------------
    
    @field_validator(
        "CORS_ORIGINS",
        "GOOGLE_API_KEYS",
        "ALLOWED_API_KEYS",
        "ALLOWED_SCREENSHOT_MIME_TYPES",
        "CORS_ALLOW_METHODS",
        "CORS_ALLOW_HEADERS",
        mode="before"
    )
    @classmethod
    def parse_list_fields(cls, v):
        if isinstance(v, str):
            v_stripped = v.strip()
            if v_stripped.startswith("[") and v_stripped.endswith("]"):
                import json
                try:
                    return json.loads(v_stripped)
                except Exception:
                    pass
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @model_validator(mode="after")
    def validate_production_settings(self):
        """Enforce stricter validation in production."""
        supported_image_types = {"image/png", "image/jpeg", "image/webp"}
        unsupported_mime_types = set(self.ALLOWED_SCREENSHOT_MIME_TYPES) - supported_image_types
        if unsupported_mime_types:
            raise ValueError(
                f"Unsupported screenshot MIME types configured: {sorted(unsupported_mime_types)}"
            )

        if self.is_production:
            # Require API authentication in production
            if not self.API_SECRET_KEY and not self.ALLOWED_API_KEYS:
                raise ValueError(
                    "API authentication must be configured in production"
                )
            
            # Require specific CORS origins
            if "*" in self.CORS_ORIGINS:
                raise ValueError(
                    "Wildcard CORS origins not allowed in production"
                )
            
            # Require at least one LLM API key
            if not self.effective_api_keys:
                raise ValueError(
                    "At least one Google API key required in production"
                )

            if not self.ENABLE_SANDBOX_EXECUTION:
                raise ValueError(
                    "Sandboxed execution must be enabled in production"
                )

            if (
                not self.SANDBOX_USE_DOCKER
                and not self.ALLOW_UNSAFE_HOST_EXECUTION_IN_PRODUCTION
            ):
                raise ValueError(
                    "Production executor requires Docker sandboxing or an explicit host-execution override"
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


def clear_settings_cache():
    """Clear the settings cache (useful for testing)."""
    get_settings.cache_clear()


# Global settings singleton
settings = get_settings()
