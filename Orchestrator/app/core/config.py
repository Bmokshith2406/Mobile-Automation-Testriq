from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    GENERATOR_URL: str = Field(..., env="GENERATOR_URL")
    GENERATOR_API_KEY: str = Field(..., env="GENERATOR_API_KEY")
    EXECUTOR_URL: str = Field(..., env="EXECUTOR_URL")
    EXECUTOR_API_KEY: str = Field(..., env="EXECUTOR_API_KEY")
    REPORTER_URL: str = Field(..., env="REPORTER_URL")
    REPORTER_API_KEY: str = Field(..., env="REPORTER_API_KEY")

    TESTCASES_RAG_URL: str = Field(..., env="TESTCASES_RAG_URL")
    TESTCASES_RAG_API_KEY: str = Field(..., env="TESTCASES_RAG_API_KEY")
    TESTCASES_RAG_ADMIN_API_KEY: str = Field("", env="TESTCASES_RAG_ADMIN_API_KEY")
    METHODS_RAG_URL: str = Field(..., env="METHODS_RAG_URL")
    METHODS_RAG_API_KEY: str = Field(..., env="METHODS_RAG_API_KEY")
    REPORTS_RAG_URL: str = Field(..., env="REPORTS_RAG_URL")
    REPORTS_RAG_API_KEY: str = Field(..., env="REPORTS_RAG_API_KEY")
    EXTRACTOR_URL: str = Field(..., env="EXTRACTOR_URL")
    EXTRACTOR_API_KEY: str = Field(..., env="EXTRACTOR_API_KEY")

    MONGO_URI: str = Field("mongodb://localhost:27017", env="MONGO_URI")
    MONGO_DB: str = Field("orchestrator_db", env="MONGO_DB")

    # Operational knobs
    MAX_CONCURRENT_RUNS: int = Field(5, env="MAX_CONCURRENT_RUNS")
    DOWNSTREAM_TIMEOUT_SECONDS: int = Field(900, env="DOWNSTREAM_TIMEOUT_SECONDS")
    MAX_GENERATOR_BYTES: int = Field(4_000_000, env="MAX_GENERATOR_BYTES")  # 2MB
    MAX_EXECUTOR_ZIP_BYTES: int = Field(90_000_000, env="MAX_EXECUTOR_ZIP_BYTES")  # 50MB

    # Retry / circuit-breaker
    RETRY_ATTEMPTS: int = Field(3, env="RETRY_ATTEMPTS")
    RETRY_BACKOFF_BASE: float = Field(0.5, env="RETRY_BACKOFF_BASE")  # seconds
    CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = Field(7, env="CIRCUIT_BREAKER_FAILURE_THRESHOLD")
    CIRCUIT_BREAKER_COOLDOWN: int = Field(60, env="CIRCUIT_BREAKER_COOLDOWN")  # seconds

    class Config:
        env_file = ".env"

settings = Settings()
