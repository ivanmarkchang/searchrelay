"""Public contracts. Provider content is data, never instructions."""
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchRequest(Model):
    query: str = Field(min_length=1, max_length=400)
    mode: Literal["web", "articles", "video"] = "web"
    limit: int = Field(default=5, ge=1, le=10)
    freshness: Literal["day", "week", "month", "year"] | None = None
    include_domains: list[str] = Field(default_factory=list, max_length=20)
    exclude_domains: list[str] = Field(default_factory=list, max_length=20)
    strict_dates: bool = False

    @field_validator("query")
    @classmethod
    def query_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value.strip()

    @field_validator("include_domains", "exclude_domains")
    @classmethod
    def domains(cls, values: list[str]) -> list[str]:
        normalized = []
        for value in values:
            host = value.lower().strip().rstrip(".").encode("idna").decode()
            if not host or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789.-" for c in host):
                raise ValueError("domain filters must be hostnames, without URL paths or operators")
            if any(not p or p.startswith("-") or p.endswith("-") for p in host.split(".")):
                raise ValueError("invalid domain")
            normalized.append(host)
        return normalized


class Result(Model):
    title: str
    url: str
    snippet: str = ""
    provider: str
    upstream_engine: str = "unknown"
    kind: Literal["web", "article", "video"] = "web"
    published_at: datetime | None = None
    date_status: Literal["verified", "provider_reported", "inferred", "unknown"] = "unknown"
    date_source: str | None = None
    date_raw: str | None = None
    retrieved_at: datetime = Field(default_factory=utcnow)

    @field_validator("url")
    @classmethod
    def safe_url(cls, value: str) -> str:
        url = urlsplit(value)
        if url.scheme not in {"https", "http"} or not url.hostname or url.username or url.password:
            raise ValueError("result must have an HTTP(S) URL without credentials")
        return value


class Attempt(Model):
    provider: str
    outcome: str
    reason: str | None = None
    elapsed_ms: int = 0
    retry_at: datetime | None = None


class SearchResponse(Model):
    status: Literal["useful", "empty", "unavailable"]
    results: list[Result] = Field(default_factory=list)
    attempts: list[Attempt] = Field(default_factory=list)
    cached: bool = False
    untrusted: bool = True
    warnings: list[str] = Field(default_factory=list)

