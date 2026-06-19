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
    if value is None:
        return default

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _env_list(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _validate_required_env_vars() -> dict:
    """Validate all required environment variables at startup."""
    required_vars = {
        "GOOGLE_API_KEY": "Gemini API key",
        "MONGO_CONNECTION_STRING": "MongoDB connection URI",
        "API_KEY": "API authentication key",
    }
    
    missing_vars = {}
    for var_name, description in required_vars.items():
        value = os.getenv(var_name)
        if not value or value.strip() == "":
            missing_vars[var_name] = description
    
    if missing_vars:
        error_msg = "Missing required environment variables:\n"
        for var, desc in missing_vars.items():
            error_msg += f"  - {var} ({desc})\n"
        raise ValueError(error_msg)
    
    return {k: os.getenv(k) for k in required_vars.keys()}


class Settings:
    DEFAULT_JWT_SECRET = "replace-this-with-a-long-random-secret"

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------

    APP_NAME: str = "Intelligent Automation Methods Search Platform"
    VERSION: str = "1.0.0"
    CREATED_BY: str = "MOKSHITH BALIDI"

    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
    MONGO_CONNECTION_STRING: str = os.getenv("MONGO_CONNECTION_STRING", "")
    API_KEY: str = os.getenv("API_KEY", "change-me-in-production")
    ADMIN_API_KEY: str = os.getenv("ADMIN_API_KEY", "change-me-admin")
    TRUST_FORWARDED_IP: bool = _env_bool("TRUST_FORWARDED_IP", False)

    DB_NAME: str = "python_playwright_methods_db"
    COLLECTION_SCRIPT_METHODS: str = "playwright_python_methods"
    COLLECTION_USERS: str = "users"
    COLLECTION_AUDIT: str = "api_audit_logs"

    # ------------------------------------------------------------------
    # Embeddings / Vector Search
    # ------------------------------------------------------------------

    EMBEDDING_MODEL_NAME: str = "all-MiniLM-L6-v2"
    VECTOR_INDEX_NAME: str = "vector_index"

    CANDIDATES_TO_RETRIEVE: int = 15
    FINAL_RESULTS: int = 5
    TOP_K: int = 3

    # ------------------------------------------------------------------
    # Gemini Controls
    # ------------------------------------------------------------------

    GEMINI_RERANK_ENABLED: bool = _env_bool("GEMINI_RERANK_ENABLED", True)
    QUERY_EXPANSION_ENABLED: bool = _env_bool("QUERY_EXPANSION_ENABLED", True)
    GEMINI_LLM_MODEL: str = os.getenv("LLM_MODEL_NAME", os.getenv("GEMINI_LLM_MODEL", "gemini-2.5-flash"))
    LLM_FALLBACK_MODEL: str = os.getenv("LLM_FALLBACK_MODEL", "gemini-2.5-flash")
    QUERY_EXPANSIONS: int = _env_int("QUERY_EXPANSIONS", 6)
    DIVERSITY_ENFORCE: bool = _env_bool("DIVERSITY_ENFORCE", True)
    DIVERSITY_PER_FEATURE: bool = _env_bool("DIVERSITY_PER_FEATURE", True)
    MAX_CONCURRENT_LLM_CALLS: int = _env_int("MAX_CONCURRENT_LLM_CALLS", 8)

    # Retry configuration with exponential backoff
    GEMINI_RETRIES: int = _env_int("GEMINI_RETRIES", 3)
    GEMINI_RETRY_BASE_DELAY: float = _env_float("GEMINI_RETRY_BASE_DELAY", 1.0)
    GEMINI_RETRY_MAX_DELAY: float = _env_float("GEMINI_RETRY_MAX_DELAY", 30.0)
    GEMINI_TIMEOUT: float = _env_float("GEMINI_TIMEOUT", 60.0)
    GEMINI_RATE_LIMIT_SLEEP: float = _env_float("GEMINI_RATE_LIMIT_SLEEP", 0.1)

    CACHE_TTL_SECONDS: int = _env_int("CACHE_TTL_SECONDS", 60 * 5)

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    # Removed JWT
    
    # CORS Configuration
    CORS_ALLOWED_ORIGINS: list[str] = _env_list(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:3000,http://localhost:8000",
    )
    
    # Request size limits
    MAX_UPLOAD_FILE_SIZE_MB: int = _env_int("MAX_UPLOAD_FILE_SIZE_MB", 50)
    MAX_REQUEST_BODY_SIZE_MB: int = _env_int("MAX_REQUEST_BODY_SIZE_MB", 10)
    
    # Database configuration
    DB_POOL_MIN_SIZE: int = _env_int("DB_POOL_MIN_SIZE", 5)
    DB_POOL_MAX_SIZE: int = _env_int("DB_POOL_MAX_SIZE", 20)
    
    # Redis Cache (optional)
    REDIS_URL: str = os.getenv("REDIS_URL", "")
    USE_REDIS_CACHE: bool = bool(os.getenv("REDIS_URL"))
    
    # Rate limiting
    RATE_LIMIT_PER_MINUTE: int = _env_int("RATE_LIMIT_PER_MINUTE", 60)
    
    # Environment detection
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    DEBUG: bool = _env_bool("DEBUG", ENVIRONMENT == "development")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
    LOG_FORMAT: str = os.getenv("LOG_FORMAT", "text").lower()

    # Resilience
    FAIL_FAST_STARTUP: bool = _env_bool("FAIL_FAST_STARTUP", True)

    # Request tracing
    ENABLE_TRACING: bool = _env_bool("ENABLE_TRACING", False)
    TRACE_SAMPLE_RATE: float = _env_float("TRACE_SAMPLE_RATE", 0.1)

    # ------------------------------------------------------------------
    # ------------------- LLM PROMPT TEMPLATES --------------------------
    # ------------------------------------------------------------------

    Method_MADL_Prompt = """
                Analyze this raw {framework_label} {language_label} automation method and return STRICT JSON only with this schema:

                {{
                  "method_name": "",
                  "method_documentation": {{
                    "summary": "",
                "description": "",
                "reusable": true,
                "intent": "",
                "params": {{ "param": "description" }},
                "applies": "",
                "returns": "",
                "keywords": [],
                "owner": "QE-Core/Automation",
                "example_usage": "",
                "created": "",
                "last_updated": ""
              }}
            }}

            Rules:
            - Summary must contain 30–35 words maximum.
            - Total keywords must not exceed 10–15.
            - Never lose the core automation intent.
                - Response MUST be valid JSON only.
                - method_name must contain the complete function signature.
                - params must match the method arguments present in the snippet.
                - returns must be "None" if nothing is returned.
                - keywords should be relevant to the automation intent, framework, and code patterns shown.

            RAW METHOD:
            {raw_method}
            """


    Query_Normalization_Prompt = """
            This is a query that I received from a user for automation method searching.

            Rules:
            - Preserve user intent strictly.
            - Correct spelling and minor grammar only.
            - Do NOT paraphrase or expand meaning.
            - Keep wording nearly identical.
            - Return ONLY ONE corrected sentence.

            Query:
            "{query}"
            """


    Query_Expansion_Prompt = """
            You are an assistant that expands user search queries into useful paraphrases and synonyms for automation methods search that happens on RAG.

            Goal:
            - Increase semantic coverage without changing original intent.

            Instructions:
            - Return only ONE comma-separated single line of EXACTLY {n} short query variants.
            - No numbering.
            - No bullet points.

            Query:
            "{normalized_query}"
            """


    Results_ReRanking_Prompt = """
            You are an expert relevance-ranking assistant.

            Task:
            Re-rank the following automation methods based only on alignment with the user query.

            User Query:
            "{query}"

            Output rules:
            - Return ONLY a newline-separated list of candidate _id values.
            - Exactly one _id per line.
            - Order IDs from MOST relevant to LEAST relevant.
            - Do not add commentary or extra text.

            Candidates:
            """


    Final_Ranking_Prompt = """
            From these automation methods, select the TOP {top_k} that best match what the user wants to automate.

            Judge only on functional automation relevance.

            User Query:
            "{query}"

            STRICT output rules:
            - Provide EXACTLY {top_k} lines.
            - Each line format:

            <method_id> | <confidence_score>

            Where:
            - confidence_score is between 0 and 100.
            - Highest confidence first.
            - No extra commentary or formatting.

            Methods:
            """


    # ------------------------------------------------------------------
    # Deduplication Prompts
    # ------------------------------------------------------------------

    Dedupe_Summary_Prompt = """
            Analyze the following automation method.

            Produce EXACTLY a 12-word single sentence summary describing the automation intent only.

            Rules:
            - EXACTLY 12 words.
            - Single sentence.
            - No punctuation at end.
            - No quotes, bullet points, or numbering.
            - Absolutely no explanations.

            Raw Method:
            "{raw_method}"

            Return ONLY the 12-word summary.
            """


    Dedupe_Verification_Prompt = """
            You are an automation method duplication detection expert.

            Compare the NEW METHOD with the EXISTING METHODS below.

            Determine whether ANY existing method performs the SAME FUNCTIONAL AUTOMATION
            INTENT using a SUBSTANTIALLY IDENTICAL workflow.

            Reasoning rules:
            - Method names may differ.
            - If PARAMETERS differ → treat as UNIQUE.
            - If LOCATORS differ → treat as UNIQUE.
            - If ASYNC FLOW or WAIT STRATEGY differs → treat as UNIQUE.

            Reply with EXACTLY one word:

            DUPLICATE
            or
            UNIQUE

            No explanation allowed.

            NEW METHOD
            Method Name: "{new_method_name}"
            Raw Method:
            "{new_raw_method}"

            EXISTING METHODS
            -----------------
            {existing_blocks}
            """


    def validate(self):
        """Validate all critical settings at initialization."""
        errors = []
        
        if not self.GOOGLE_API_KEY:
            errors.append("GOOGLE_API_KEY is required")
        
        if not self.MONGO_CONNECTION_STRING:
            errors.append("MONGO_CONNECTION_STRING is required")
        
        if self.API_KEY == "change-me-in-production":
            errors.append("API_KEY must be configured")
            
        if self.MAX_CONCURRENT_LLM_CALLS < 1:
            errors.append("MAX_CONCURRENT_LLM_CALLS must be >= 1")
        
        if self.DB_POOL_MAX_SIZE < self.DB_POOL_MIN_SIZE:
            errors.append("DB_POOL_MAX_SIZE must be >= DB_POOL_MIN_SIZE")

        if self.RATE_LIMIT_PER_MINUTE < 1:
            errors.append("RATE_LIMIT_PER_MINUTE must be >= 1")

        if not 0.0 <= self.TRACE_SAMPLE_RATE <= 1.0:
            errors.append("TRACE_SAMPLE_RATE must be between 0.0 and 1.0")

        if self.LOG_FORMAT not in {"text", "json"}:
            errors.append("LOG_FORMAT must be either 'text' or 'json'")
        
        if errors:
            msg = "Configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
            if self.FAIL_FAST_STARTUP:
                raise ValueError(msg)
            else:
                print(f"WARNING: {msg}")

def assert_valid_startup_settings(settings: Settings) -> None:
    settings.validate()


# ----------------------------------------------------------------------
# Settings Loader
# ----------------------------------------------------------------------

_settings_instance = None

@lru_cache
def get_settings() -> Settings:
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
        _settings_instance.validate()
    return _settings_instance
