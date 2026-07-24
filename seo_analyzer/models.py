from enum import StrEnum
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from seo_analyzer.utils import normalize_url


def _public_web_url_shape(value: str) -> str:
    value = value.strip()
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("URL is malformed") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ValueError("credentials in URLs are not allowed")
    return value


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class Impact(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Effort(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PageType(StrEnum):
    HOME = "home"
    PRICING = "pricing"
    FEATURE = "feature"
    USE_CASE = "use_case"
    INDUSTRY = "industry"
    INTEGRATION = "integration"
    COMPARISON = "comparison"
    ALTERNATIVE = "alternative"
    TEMPLATE = "template"
    FREE_TOOL = "free_tool"
    BLOG = "blog"
    GUIDE = "guide"
    GLOSSARY = "glossary"
    DOCS = "docs"
    CASE_STUDY = "case_study"
    SECURITY = "security"
    CHANGELOG = "changelog"
    ABOUT = "about"
    CAREERS = "careers"
    LEGAL = "legal"
    LOGIN = "login"
    OTHER = "other"


class Issue(BaseModel):
    code: str
    category: str
    severity: Severity
    title: str
    explanation: str
    recommendation: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    penalty: float = Field(default=0, ge=0, le=100)
    impact: Impact = Impact.MEDIUM
    effort: Effort = Effort.MEDIUM
    confidence: float = Field(default=1.0, ge=0, le=1)
    direct_ranking_factor: bool | None = None


class Recommendation(BaseModel):
    code: str
    priority: int = Field(ge=0, le=100)
    impact: Impact
    effort: Effort
    confidence: float = Field(ge=0, le=1)
    title: str
    action: str
    why: str
    validation: str
    affected_pages: int = Field(default=1, ge=1)
    issue_codes: list[str] = Field(default_factory=list)


class ScoreBreakdown(BaseModel):
    overall: float = Field(ge=0, le=100)
    grade: str
    rating: str
    categories: dict[str, float]
    weights: dict[str, float]
    methodology_version: str = "2026.1"


class PageAnalysis(BaseModel):
    schema_version: str = "2.0"
    analyzed_at: str
    requested_url: str
    final_url: str
    page_type: dict[str, Any]
    fetch: dict[str, Any]
    indexability: dict[str, Any]
    metadata: dict[str, Any]
    headings: dict[str, Any]
    content: dict[str, Any]
    links: dict[str, Any]
    images: dict[str, Any]
    social: dict[str, Any]
    structured_data: dict[str, Any]
    international: dict[str, Any]
    mobile: dict[str, Any]
    performance: dict[str, Any]
    saas: dict[str, Any]
    score: ScoreBreakdown
    issues: list[Issue]
    recommendations: list[Recommendation]
    limitations: list[str]


class SiteAuditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=4, max_length=2_048)
    max_pages: int = Field(default=25, ge=1, le=200)
    max_depth: int = Field(default=3, ge=0, le=8)
    concurrency: int = Field(default=5, ge=1, le=10)
    respect_robots: bool = True
    include_subdomains: bool = False
    include_query_parameters: bool = False
    use_sitemap: bool = True

    @field_validator("url")
    @classmethod
    def valid_url_shape(cls, value: str) -> str:
        return _public_web_url_shape(value)


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    urls: list[str] = Field(min_length=2, max_length=8)
    include_pagespeed: bool = False

    @field_validator("urls")
    @classmethod
    def unique_urls(cls, urls: list[str]) -> list[str]:
        cleaned = [_public_web_url_shape(url) for url in urls]
        if len({normalize_url(url) for url in cleaned}) != len(cleaned):
            raise ValueError("urls must be unique")
        return cleaned


class OpportunityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=4, max_length=2_048)
    impressions: float = Field(default=0, ge=0)
    clicks: float = Field(default=0, ge=0)
    average_position: float | None = Field(default=None, ge=1)
    conversions: float = Field(default=0, ge=0)
    conversion_value: float = Field(default=0, ge=0)
    business_value: int = Field(default=3, ge=1, le=5)

    @field_validator("url")
    @classmethod
    def valid_url_shape(cls, value: str) -> str:
        return _public_web_url_shape(value)

    @model_validator(mode="after")
    def consistent_search_metrics(self) -> "OpportunityInput":
        if self.clicks > self.impressions:
            raise ValueError("clicks cannot exceed impressions")
        return self


class OpportunityRequest(BaseModel):
    """First-party metrics used to rank pages without pretending to know SERP data."""

    model_config = ConfigDict(extra="forbid")

    pages: list[OpportunityInput] = Field(min_length=1, max_length=500)
    target_ctr: float | None = Field(default=None, gt=0, le=1)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    model: Literal["balanced", "traffic", "revenue"] = "balanced"

    @field_validator("currency")
    @classmethod
    def valid_currency(cls, value: str) -> str:
        if not value.isascii() or not value.isalpha():
            raise ValueError("currency must be a three-letter code")
        return value.upper()

    @field_validator("pages")
    @classmethod
    def unique_pages(cls, pages: list[OpportunityInput]) -> list[OpportunityInput]:
        identities = [normalize_url(page.url) for page in pages]
        if len(set(identities)) != len(identities):
            raise ValueError("page URLs must be unique")
        return pages


class ErrorResponse(BaseModel):
    error: dict[str, Any]
