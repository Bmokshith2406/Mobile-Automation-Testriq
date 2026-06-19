from typing import List, Optional
from pydantic import BaseModel, Field

# -------------------------------------------------------------------
# Auth models
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
# Testcase update
# -------------------------------------------------------------------

class UpdateTestCaseRequest(BaseModel):
    feature: Optional[str] = None
    summary: Optional[str] = None
    description: Optional[str] = None
    prerequisites: Optional[str] = None
    steps: Optional[str] = None
    keywords: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    priority: Optional[str] = Field(
        default=None,
        description="Low/Medium/High/Critical",
    )
    platform: Optional[str] = None
    popularity: Optional[float] = None

    # NEW: optional link update
    playwright_script_id: Optional[str] = None
    script_framework: Optional[str] = None
    script_language: Optional[str] = None


# -------------------------------------------------------------------
# Search schemas
# -------------------------------------------------------------------

class SearchRequest(BaseModel):
    query: str
    feature: Optional[str] = None
    tags: Optional[List[str]] = None
    priority: Optional[str] = None
    platform: Optional[str] = None
    ranking_variant: str = Field(
        default="A",
        description="A=original scoring, B=enhanced scoring",
    )


class SearchResultItem(BaseModel):
    id: str
    probability: float
    test_case_id: str
    feature: str
    description: str
    prerequisites: str
    steps: str
    summary: str
    keywords: List[str]
    tags: List[str] = []
    priority: Optional[str] = None
    platform: Optional[str] = None

    # NEW: script linkage
    playwright_script_id: Optional[str] = None
    script_framework: Optional[str] = None
    script_language: Optional[str] = None


class SearchResponse(BaseModel):
    query: str
    feature_filter: Optional[str]
    results_count: int
    results: List[SearchResultItem]
    from_cache: bool
    ranking_variant: str


# -------------------------------------------------------------------
# Playwright Script Models
# -------------------------------------------------------------------

class PlaywrightScriptCreate(BaseModel):
    testcase_id: str = Field(..., description="Human readable Test Case ID")
    testcase_object_id: str = Field(..., description="Stored document ID of testcase")
    script: str = Field(..., description="Raw Playwright script content")
    framework: Optional[str] = Field(None, description="Stored framework for this script")
    language: Optional[str] = Field(None, description="Stored language for this script")


class PlaywrightScriptUpdate(BaseModel):
    script: Optional[str] = Field(None, description="Updated raw Playwright script")
    framework: Optional[str] = Field(None, description="Updated framework for this script")
    language: Optional[str] = Field(None, description="Updated language for this script")


class PlaywrightScriptOut(BaseModel):
    id: str
    testcase_id: str
    testcase_object_id: str
    script: str
    framework: Optional[str] = None
    language: Optional[str] = None
    created_at: str
