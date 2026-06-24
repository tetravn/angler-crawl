"""Pydantic models cho request Firecrawl. extra='ignore' để bỏ qua field lạ."""
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ScrapeOptions(BaseModel):
    model_config = ConfigDict(extra="ignore")

    formats: list[str] = Field(default_factory=lambda: ["markdown"])
    onlyMainContent: bool = True
    waitFor: int = 0
    timeout: int = 30000
    headers: dict | None = None
    egress: str | None = None
    fallback: str | None = None  # P10: opt-in "jina"|"firecrawl" khi local bó tay


class ScrapeRequest(ScrapeOptions):
    url: str


class MapRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str
    search: str | None = None
    limit: int = 0
    includeSubdomains: bool = False


class CrawlRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str
    limit: int = 10
    maxDepth: int = 2
    includePaths: list[str] | None = None
    excludePaths: list[str] | None = None
    allowExternalLinks: bool = False
    scrapeOptions: ScrapeOptions | None = None
    egress: str | None = None


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    query: str
    limit: int = 10
    lang: str | None = None
    categories: list[str] | None = None  # None → SEARCH_CATEGORIES (mặc định gồm "science")
    scrapeOptions: ScrapeOptions | None = None
    egress: str | None = None


class BatchScrapeRequest(ScrapeOptions):
    urls: list[str]


class ExtractRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    urls: list[str]
    prompt: str | None = None
    # 'schema' trùng tên thuộc tính của BaseModel → dùng alias.
    schema_: dict[str, Any] | None = Field(default=None, alias="schema")


class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    query: str
    categories: list[str] | None = None  # mặc định general+news+science
    languages: list[str] | None = None
    sites: list[str] | None = None  # nguồn "nhiều phía" buộc gồm
    maxPerDomain: int = 2
    limit: int = 24
    scrape: bool = False  # True = scrape nội dung mỗi nguồn (+ cờ blocked)
    analyze: bool = False  # #9 so chéo nguồn bằng LLM (ép scrape=True)
    egress: str | None = None


class DeepResearchRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    query: str
    maxIterations: int = 3
    maxQueries: int = 4
    maxSourcesPerQuery: int = 5
    maxScrapePerIteration: int = 6
    egress: str | None = None


class TranscriptRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    urls: list[str]
    languages: list[str] | None = None
    egress: str | None = None


class MonitorRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str
    intervalSeconds: int | None = None
    scrapeOptions: ScrapeOptions | None = None
    egress: str | None = None


class AgentRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str
    prompt: str
    maxSteps: int = 15
    egress: str | None = None
