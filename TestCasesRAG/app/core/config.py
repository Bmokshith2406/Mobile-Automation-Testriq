import os
from functools import lru_cache
from dotenv import load_dotenv

# Safe dotenv loading
try:
    load_dotenv()
except Exception:
    pass


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return int(value)


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return float(value)


class Settings:
    APP_NAME: str = "Intelligent Test Case Search API (MongoDB Edition)"
    VERSION: str = "1.0"
    CREATED_BY: str = "MOKSHITH BALIDI"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development").strip().lower()
    FAIL_FAST_STARTUP: bool = _env_bool("FAIL_FAST_STARTUP", True)

    GOOGLE_API_KEY: str | None = os.getenv("GOOGLE_API_KEY")
    OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")
    ANTHROPIC_API_KEY: str | None = os.getenv("ANTHROPIC_API_KEY")
    LOCAL_LLM_API_KEY: str | None = os.getenv("LOCAL_LLM_API_KEY")
    MONGO_CONNECTION_STRING: str = os.getenv("MONGO_CONNECTION_STRING", "")
    API_KEY: str = os.getenv("API_KEY", "change-me-in-production")
    ADMIN_API_KEY: str = os.getenv("ADMIN_API_KEY", "change-me-admin")
    TRUST_FORWARDED_IP: bool = _env_bool("TRUST_FORWARDED_IP", False)
    REQUIRE_GEMINI_ON_STARTUP: bool = _env_bool("REQUIRE_GEMINI_ON_STARTUP", False)
    ALLOW_PUBLIC_USER_REGISTRATION: bool = _env_bool(
        "ALLOW_PUBLIC_USER_REGISTRATION",
        False,
    )
    CORS_ALLOWED_ORIGINS_RAW: str = os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:5173,http://127.0.0.1:5173",
    )
    CORS_ALLOWED_ORIGINS: list[str] = [
        origin.strip()
        for origin in CORS_ALLOWED_ORIGINS_RAW.split(",")
        if origin.strip()
    ]

    DB_NAME: str = "Test_Cases"
    COLLECTION_TESTCASES: str = "multilevel_test_cases_mongo"
    COLLECTION_SCRIPTS: str = "playwright_scripts"
    COLLECTION_USERS: str = "users"
    COLLECTION_AUDIT: str = "api_audit_logs"
    COLLECTION_INGESTION_JOBS: str = "ingestion_jobs"

    LLM_USE_GEMINI: bool = _env_bool("LLM_USE_GEMINI", bool(os.getenv("GOOGLE_API_KEY")))
    LLM_USE_OPENAI: bool = _env_bool("LLM_USE_OPENAI", False)
    LLM_USE_ANTHROPIC: bool = _env_bool("LLM_USE_ANTHROPIC", False)
    LLM_USE_LOCAL: bool = _env_bool("LLM_USE_LOCAL", False)
    LLM_TIMEOUT_SECONDS: int = _env_int("LLM_TIMEOUT_SECONDS", 60)
    LLM_RETRIES: int = _env_int("LLM_RETRIES", 2)
    LLM_BACKOFF_BASE_SECONDS: float = _env_float("LLM_BACKOFF_BASE_SECONDS", 0.5)
    LLM_RATE_LIMIT_PER_MINUTE: int = _env_int("LLM_RATE_LIMIT_PER_MINUTE", 60)
    REQUIRE_LLM_ON_STARTUP: bool = _env_bool("REQUIRE_LLM_ON_STARTUP", False)

    GEMINI_MODEL: str = os.getenv("LLM_MODEL_NAME", os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
    LLM_FALLBACK_MODEL: str = os.getenv("LLM_FALLBACK_MODEL", "gemini-2.5-flash")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
    ANTHROPIC_BASE_URL: str = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    ANTHROPIC_VERSION: str = os.getenv("ANTHROPIC_VERSION", "2023-06-01")
    LOCAL_LLM_MODEL: str = os.getenv("LOCAL_LLM_MODEL", "")
    LOCAL_LLM_API_URL: str = os.getenv(
        "LOCAL_LLM_API_URL",
        "http://localhost:11434/v1/chat/completions",
    )
    LOCAL_LLM_API_FORMAT: str = os.getenv("LOCAL_LLM_API_FORMAT", "openai").strip().lower()
    LOCAL_LLM_EXTRA_HEADERS_JSON: str = os.getenv("LOCAL_LLM_EXTRA_HEADERS_JSON", "")

    EMBEDDING_USE_MINILM_384: bool = _env_bool("EMBEDDING_USE_MINILM_384", True)
    EMBEDDING_USE_MPNET_768: bool = _env_bool("EMBEDDING_USE_MPNET_768", False)
    EMBEDDING_USE_BGE_LARGE_1024: bool = _env_bool("EMBEDDING_USE_BGE_LARGE_1024", False)
    EMBEDDING_MODEL_NAME: str = os.getenv("EMBEDDING_MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2")
    VECTOR_INDEX_NAME: str = "vector_index"
    EMBEDDING_DIMENSIONS: int = 384
    MAX_CONCURRENT_LLM_CALLS: int = 10

    CACHE_BACKEND: str = os.getenv("CACHE_BACKEND", "auto").strip().lower()
    CACHE_KEY_PREFIX: str = os.getenv("CACHE_KEY_PREFIX", "testcasesrag")
    REDIS_URL: str | None = os.getenv("REDIS_URL")
    CANDIDATES_TO_RETRIEVE: int = 15
    FINAL_RESULTS: int = 5
    TOP_K: int = 3

    GEMINI_RERANK_ENABLED: bool = _env_bool("GEMINI_RERANK_ENABLED", True)
    GEMINI_TIMEOUT: int = _env_int("GEMINI_TIMEOUT", LLM_TIMEOUT_SECONDS)
    QUERY_EXPANSION_ENABLED: bool = _env_bool("QUERY_EXPANSION_ENABLED", True)
    QUERY_EXPANSIONS: int = _env_int("QUERY_EXPANSIONS", 6)
    DIVERSITY_ENFORCE: bool = _env_bool("DIVERSITY_ENFORCE", True)
    DIVERSITY_PER_FEATURE: bool = _env_bool("DIVERSITY_PER_FEATURE", True)
    GEMINI_RATE_LIMIT_SLEEP: float = _env_float("GEMINI_RATE_LIMIT_SLEEP", 0.5)
    GEMINI_RETRIES: int = _env_int("GEMINI_RETRIES", LLM_RETRIES)

    CACHE_TTL_SECONDS: int = _env_int("CACHE_TTL_SECONDS", 60 * 5)
    CACHE_MAX_SIZE: int = _env_int("CACHE_MAX_SIZE", 1000)
    CACHE_ENABLED: bool = _env_bool("CACHE_ENABLED", True)

    RATE_LIMIT_REQUESTS_PER_MINUTE: int = _env_int("RATE_LIMIT_REQUESTS_PER_MINUTE", 60)
    RATE_LIMIT_BURST_SIZE: int = _env_int("RATE_LIMIT_BURST_SIZE", 100)
    RATE_LIMIT_STORAGE: str = "memory"

    MAX_REQUEST_SIZE_MB: int = _env_int("MAX_REQUEST_SIZE_MB", 100)
    MAX_QUERY_LENGTH: int = _env_int("MAX_QUERY_LENGTH", 5000)
    MAX_FILE_SIZE_MB: int = _env_int("MAX_FILE_SIZE_MB", 10)
    REQUEST_TIMEOUT_SECONDS: int = _env_int("REQUEST_TIMEOUT_SECONDS", 30)

    CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = _env_int("CIRCUIT_BREAKER_FAILURE_THRESHOLD", 5)
    CIRCUIT_BREAKER_RECOVERY_TIMEOUT: int = _env_int("CIRCUIT_BREAKER_RECOVERY_TIMEOUT", 60)

    MAX_RETRIES: int = _env_int("MAX_RETRIES", 3)
    RETRY_BACKOFF_FACTOR: float = _env_float("RETRY_BACKOFF_FACTOR", 2.0)
    RETRY_MAX_WAIT: int = _env_int("RETRY_MAX_WAIT", 30)

    DB_QUERY_TIMEOUT: int = _env_int("DB_QUERY_TIMEOUT", 30)
    DB_CONNECT_TIMEOUT: int = _env_int("DB_CONNECT_TIMEOUT", 10)

    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT: str = "json"

    ENABLE_METRICS: bool = _env_bool("ENABLE_METRICS", True)
    METRICS_PORT: int = _env_int("METRICS_PORT", 9090)

    ENABLE_TRACING: bool = _env_bool("ENABLE_TRACING", True)
    TRACE_SAMPLE_RATE: float = _env_float("TRACE_SAMPLE_RATE", 0.1)

    ENABLE_GEMINI_RERANK: bool = _env_bool("ENABLE_GEMINI_RERANK", True)
    ENABLE_QUERY_EXPANSION: bool = _env_bool("ENABLE_QUERY_EXPANSION", True)
    ENABLE_DIVERSITY_ENFORCEMENT: bool = _env_bool("ENABLE_DIVERSITY_ENFORCEMENT", True)
    ENABLE_SOFT_DELETE: bool = _env_bool("ENABLE_SOFT_DELETE", True)
    ENABLE_AUDIT_LOGGING: bool = _env_bool("ENABLE_AUDIT_LOGGING", True)
    ENABLE_REQUEST_COMPRESSION: bool = _env_bool("ENABLE_REQUEST_COMPRESSION", True)

    INGESTION_WORKER_COUNT: int = _env_int("INGESTION_WORKER_COUNT", 1)
    INGESTION_QUEUE_MAX_SIZE: int = _env_int("INGESTION_QUEUE_MAX_SIZE", 100)
    INGESTION_JOB_RETENTION_HOURS: int = _env_int("INGESTION_JOB_RETENTION_HOURS", 24)

    API_PORT: int = _env_int("API_PORT", 8001)
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")

    # ------------------------------------------------------------------
    # LLM Prompt Templates (SAFE — defer substitution)
    # ------------------------------------------------------------------

    TestCase_Enrichment_Prompt = """
Analyze the following software test case end to end completely and generate enriched metadata.

Feature: "{feature}"

Test Case Description: "{description_text}"

Steps: "{steps_text}"

Output format (exactly):
Summary: Exactly 30 words clearly explaining purpose and process of the test case.
Keywords: Exactly 20 key words & phrases together, they shall be comma-separated.
"""

    Query_Normalization_Prompt = """
This is a query that I have received from a user for test case searching.

Most important:
- Do not lose user intent.
- Do not lose requested action.
- Fix only spelling or minor grammar errors.
- Preserve wording and meaning.
- Return ONLY a single corrected sentence.

Query: "{query}"
"""

    Query_Expansion_Prompt = """
You are an assistant that expands short search queries into useful
paraphrases and synonyms for software test-case search.

Goal:
- Widen semantic scope while preserving intent.

Instructions:
- Return only a comma-separated single line of {n} short paraphrases or keywords.
- Do NOT use numbering or bullet points.

Query: "{normalized_query}"
"""

    Results_ReRanking_Prompt = """
You are an expert relevance-ranking assistant.

Your task:
Re-rank the following test cases based on how well each one matches the given query.

Query:
"{query}"

Instructions:
- Return ONLY a newline-separated list of candidate IDs.
- Each line must contain exactly one candidate _id.
- Order the IDs from MOST relevant to LEAST relevant.
- Do NOT include any explanations, commentary, formatting, or extra text.

Candidates:
"""

    Final_Ranking_Prompt = """
Look at these software test cases and choose the {top_k} that best match what the user really wants to test.

Ignore any previous scores, rankings, or ordering. Judge only by how well each test case matches the user’s intent.

User Query:
"{query}"

Reply with EXACTLY {top_k} lines.
Format each line as:

<test_case_id> | <confidence_score>

Where:
- <confidence_score> is an integer between 0 and 100 showing how well the test matches the user’s intent.
- Put the best match first.
- Do not add any other text.

Test cases:
"""

    Dedupe_Summary_Prompt = """
Analyze the following end-to-end software test case.

Your task:
Generate EXACTLY a 12-word summary describing only the functional intent of the test case.

Rules:
- EXACTLY 12 words (no more, no less).
- Single sentence.
- No quotes, bullet points, or numbering.
- No punctuation at end.
- No explanations or extra words.

Feature:
"{feature}"

Description:
"{description_text}"

Steps:
"{steps_text}"

Return ONLY the 12-word summary.
"""

    Dedupe_Verification_Prompt = """
You are an expert QA test-case duplication detector.

Compare the NEW TEST CASE with the EXISTING TEST CASES below.

Determine if ANY existing test case validates the SAME FUNCTIONAL INTENT
with SUBSTANTIALLY THE SAME WORKFLOW.

Reply with EXACTLY one word only:

DUPLICATE
or
UNIQUE

Do NOT explain.

NEW TEST CASE
Feature: "{new_feature}"
Description: "{new_description}"
Steps:
"{new_steps}"

EXISTING TEST CASES
-------------------
{existing_blocks}
"""


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_enabled_llm_providers(settings: Settings | None = None) -> list[str]:
    current = settings or get_settings()
    providers = []

    if current.LLM_USE_GEMINI:
        providers.append("gemini")
    if current.LLM_USE_OPENAI:
        providers.append("openai")
    if current.LLM_USE_ANTHROPIC:
        providers.append("anthropic")
    if current.LLM_USE_LOCAL:
        providers.append("local")

    return providers


def resolve_llm_provider(settings: Settings | None = None) -> str | None:
    enabled = get_enabled_llm_providers(settings)
    if len(enabled) == 1:
        return enabled[0]
    return None


def get_enabled_embedding_presets(settings: Settings | None = None) -> list[str]:
    current = settings or get_settings()
    presets = []

    if current.EMBEDDING_USE_MINILM_384:
        presets.append("minilm_384")
    if current.EMBEDDING_USE_MPNET_768:
        presets.append("mpnet_768")
    if current.EMBEDDING_USE_BGE_LARGE_1024:
        presets.append("bge_large_1024")

    return presets


def resolve_embedding_preset(settings: Settings | None = None) -> str | None:
    enabled = get_enabled_embedding_presets(settings)
    if len(enabled) == 1:
        return enabled[0]
    return None


def resolve_embedding_model_name(settings: Settings | None = None) -> str:
    current = settings or get_settings()
    preset = resolve_embedding_preset(current)

    if preset == "minilm_384":
        configured = (current.EMBEDDING_MODEL_NAME or "").strip()
        return configured or "sentence-transformers/all-MiniLM-L6-v2"

    if preset == "mpnet_768":
        return "sentence-transformers/all-mpnet-base-v2"

    if preset == "bge_large_1024":
        return "BAAI/bge-large-en-v1.5"

    return current.EMBEDDING_MODEL_NAME or "sentence-transformers/all-MiniLM-L6-v2"


def validate_startup_settings(settings: Settings | None = None) -> list[str]:
    current = settings or get_settings()
    errors: list[str] = []

    if not current.MONGO_CONNECTION_STRING.strip():
        errors.append("MONGO_CONNECTION_STRING must be configured.")

    if not current.CORS_ALLOWED_ORIGINS:
        errors.append("CORS_ALLOWED_ORIGINS must contain at least one allowed origin.")

    if "*" in current.CORS_ALLOWED_ORIGINS:
        errors.append("CORS_ALLOWED_ORIGINS cannot contain '*' when credentials are enabled.")

    if current.CACHE_ENABLED and current.CACHE_BACKEND not in {"auto", "memory", "redis"}:
        errors.append("CACHE_BACKEND must be one of: auto, memory, redis.")

    if current.CACHE_ENABLED and current.CACHE_BACKEND == "redis" and not (current.REDIS_URL or "").strip():
        errors.append("REDIS_URL must be configured when CACHE_BACKEND=redis.")

    if current.CACHE_TTL_SECONDS <= 0:
        errors.append("CACHE_TTL_SECONDS must be greater than 0.")

    if current.CACHE_MAX_SIZE <= 0:
        errors.append("CACHE_MAX_SIZE must be greater than 0.")

    if current.MAX_QUERY_LENGTH <= 0:
        errors.append("MAX_QUERY_LENGTH must be greater than 0.")

    if current.MAX_FILE_SIZE_MB <= 0:
        errors.append("MAX_FILE_SIZE_MB must be greater than 0.")

    if current.INGESTION_WORKER_COUNT <= 0:
        errors.append("INGESTION_WORKER_COUNT must be greater than 0.")

    if current.INGESTION_QUEUE_MAX_SIZE <= 0:
        errors.append("INGESTION_QUEUE_MAX_SIZE must be greater than 0.")

    if current.INGESTION_JOB_RETENTION_HOURS <= 0:
        errors.append("INGESTION_JOB_RETENTION_HOURS must be greater than 0.")

    if current.ENABLE_TRACING and not 0 <= current.TRACE_SAMPLE_RATE <= 1:
        errors.append("TRACE_SAMPLE_RATE must be between 0 and 1.")

    if current.ENVIRONMENT in {"production", "staging"}:
        if current.API_KEY == "change-me-in-production":
            errors.append("API_KEY must be changed from the default value in non-development environments.")
        if current.ADMIN_API_KEY == "change-me-admin":
            errors.append("ADMIN_API_KEY must be changed from the default value in non-development environments.")

    enabled_llm_providers = get_enabled_llm_providers(current)
    if len(enabled_llm_providers) > 1:
        errors.append(
            "Exactly one LLM provider can be enabled at a time. "
            "Set only one of LLM_USE_GEMINI, LLM_USE_OPENAI, LLM_USE_ANTHROPIC, or LLM_USE_LOCAL to true."
        )

    selected_llm_provider = resolve_llm_provider(current)
    require_llm = current.REQUIRE_LLM_ON_STARTUP or current.REQUIRE_GEMINI_ON_STARTUP

    if require_llm and selected_llm_provider is None:
        errors.append("An LLM provider must be enabled when REQUIRE_LLM_ON_STARTUP=true.")

    if selected_llm_provider == "gemini" and not (current.GOOGLE_API_KEY or "").strip():
        errors.append("GOOGLE_API_KEY must be configured when LLM_USE_GEMINI=true.")

    if selected_llm_provider == "openai" and not (current.OPENAI_API_KEY or "").strip():
        errors.append("OPENAI_API_KEY must be configured when LLM_USE_OPENAI=true.")

    if selected_llm_provider == "anthropic" and not (current.ANTHROPIC_API_KEY or "").strip():
        errors.append("ANTHROPIC_API_KEY must be configured when LLM_USE_ANTHROPIC=true.")

    if selected_llm_provider == "local" and not (current.LOCAL_LLM_API_URL or "").strip():
        errors.append("LOCAL_LLM_API_URL must be configured when LLM_USE_LOCAL=true.")
    if current.LOCAL_LLM_API_FORMAT not in {"openai", "anthropic", "generic"}:
        errors.append("LOCAL_LLM_API_FORMAT must be one of: openai, anthropic, generic.")

    enabled_embedding_presets = get_enabled_embedding_presets(current)
    if len(enabled_embedding_presets) != 1:
        errors.append(
            "Exactly one embedding preset must be enabled. "
            "Set one of EMBEDDING_USE_MINILM_384, EMBEDDING_USE_MPNET_768, or EMBEDDING_USE_BGE_LARGE_1024 to true."
        )

    return errors


def assert_valid_startup_settings(settings: Settings | None = None) -> None:
    errors = validate_startup_settings(settings)
    if errors:
        raise RuntimeError("Invalid startup configuration:\n- " + "\n- ".join(errors))
