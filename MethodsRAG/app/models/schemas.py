from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.code_provenance import normalize_framework, normalize_language

# -------------------------------------------------------------------
# AUTH MODELS  (UNCHANGED)
# -------------------------------------------------------------------

class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "viewer"  # "admin" | "editor" | "viewer"


class UserLogin(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: str
    username: str
    role: str


# -------------------------------------------------------------------
# METHOD UPDATE MODEL
# -------------------------------------------------------------------

class UpdateMethodRequest(BaseModel):
    """
    Allows controlled updates to MADL documentation.
    Raw method code should be immutable after creation.
    """

    model_config = ConfigDict(extra="forbid")

    summary: Optional[str] = None
    description: Optional[str] = None
    intent: Optional[str] = None
    applies: Optional[str] = None
    returns: Optional[str] = None

    params: Optional[Dict[str, str]] = None
    keywords: Optional[List[str]] = None

    owner: Optional[str] = None
    example_usage: Optional[str] = None
    reusable: Optional[bool] = None
    framework: Optional[str] = None
    language: Optional[str] = None

    @field_validator("summary", "description", "intent", "applies", "returns", "owner", "example_usage")
    @classmethod
    def validate_optional_strings(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value

        value = value.strip()
        if not value:
            raise ValueError("String fields cannot be blank")
        return value

    @field_validator("keywords")
    @classmethod
    def validate_keywords(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return value

        normalized = [keyword.strip() for keyword in value if keyword and keyword.strip()]
        if not normalized:
            raise ValueError("keywords cannot be empty")
        return normalized

    @field_validator("framework")
    @classmethod
    def validate_framework(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value

        normalized = normalize_framework(value)
        if not normalized:
            raise ValueError("framework must be one of: playwright, selenium, cypress, appium")
        return normalized

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value

        normalized = normalize_language(value)
        if not normalized:
            raise ValueError("language must be either python or javascript")
        return normalized


# -------------------------------------------------------------------
# SEARCH REQUEST
# -------------------------------------------------------------------

class SearchRequest(BaseModel):
    """
    Query schema for METHOD search.
    """

    model_config = ConfigDict(extra="forbid")

    query: str

    owner: Optional[str] = None
    reusable: Optional[bool] = None

    keywords: Optional[List[str]] = None

    ranking_variant: str = Field(
        default="A",
        description="A=original scoring, B=enhanced scoring",
    )

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query cannot be blank")
        return value

    @field_validator("ranking_variant")
    @classmethod
    def validate_ranking_variant(cls, value: str) -> str:
        value = value.strip().upper()
        if value not in {"A", "B"}:
            raise ValueError("ranking_variant must be either 'A' or 'B'")
        return value


# -------------------------------------------------------------------
# SEARCH RESULT ITEM — METHOD VERSION
# -------------------------------------------------------------------

class SearchResultItem(BaseModel):
    """
    One ranked METHOD/MADL search result entry.
    """

    id: str
    probability: float

    method_name: str
    summary: str
    description: str
    intent: str

    params: Dict[str, str]
    applies: str
    returns: str

    keywords: List[str]

    owner: Optional[str] = None
    reusable: Optional[bool] = None
    example_usage: Optional[str] = None
    raw_code: Optional[str] = None
    framework: Optional[str] = None
    language: Optional[str] = None
    


# -------------------------------------------------------------------
# SEARCH RESPONSE
# -------------------------------------------------------------------

class SearchResponse(BaseModel):
    """
    Final API response payload for method search.
    """

    query: str

    results_count: int
    results: List[SearchResultItem]

    from_cache: bool

    ranking_variant: str
