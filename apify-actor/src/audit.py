import asyncio
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from seo_analyzer.analyzer import AnalysisArtifact, Analyzer
from seo_analyzer.crawler import SiteCrawler
from seo_analyzer.fetcher import FetchError
from seo_analyzer.models import PageAnalysis, SiteAuditRequest
from seo_analyzer.utils import normalize_url

PAGE_EVENT = "page-audited"
QUICK_EVENT = "quick-score"
BATCH_SIZE = 5
CRAWL_FIELDS = ("source", "depth", "inlinks_from_sample", "opportunity_score")


class ActorInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    urls: list[str] = Field(min_length=1, max_length=1_000)
    mode: Literal["page", "quick", "site"] = "page"
    max_pages: int = Field(default=25, ge=1, le=100, alias="maxPages")
    max_depth: int = Field(default=3, ge=0, le=8, alias="maxDepth")
    use_sitemap: bool = Field(default=True, alias="useSitemap")
    respect_robots: bool = Field(default=True, alias="respectRobots")
    include_subdomains: bool = Field(default=False, alias="includeSubdomains")

    @field_validator("urls", mode="before")
    @classmethod
    def clean_urls(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        stripped = (str(raw).strip() for raw in value)
        with_scheme = (url if "://" in url else f"https://{url}" for url in stripped if url)
        return list(dict.fromkeys(with_scheme))


class Sink(Protocol):
    def affordable(self, event: str) -> int | None: ...

    async def push(self, items: list[dict[str, Any]], event: str | None) -> None: ...


@dataclass
class RunSummary:
    audited: int = 0
    failed: int = 0
    stopped_by_budget: bool = False


class RecordingAnalyzer(Analyzer):
    """Keeps each page report so a site audit can return full per-page items."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.reports: dict[str, PageAnalysis] = {}

    async def analyze_artifact(
        self,
        url: str,
        *,
        include_pagespeed: bool = False,
        include_subdomains: bool = False,
    ) -> AnalysisArtifact:
        artifact = await super().analyze_artifact(
            url, include_pagespeed=include_pagespeed, include_subdomains=include_subdomains
        )
        key = normalize_url(artifact.report.final_url, keep_query=False)
        self.reports[key] = artifact.report
        return artifact


def _headline(report: PageAnalysis) -> dict[str, Any]:
    saas = report.saas["score"]
    return {
        "url": report.final_url,
        "title": report.metadata["title"],
        "status_code": report.fetch["status_code"],
        "seo_score": report.score.overall,
        "seo_grade": report.score.grade,
        "saas_score": saas["overall"],
        "saas_grade": saas["grade"],
        "issue_count": len(report.issues),
    }


def page_item(report: PageAnalysis, crawl: dict[str, Any] | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"type": "page", **_headline(report)}
    if crawl is not None:
        item["crawl"] = {key: crawl[key] for key in CRAWL_FIELDS}
    return item | report.model_dump(mode="json")


def quick_item(report: PageAnalysis) -> dict[str, Any]:
    return {
        "type": "quick",
        **_headline(report),
        "page_type": report.page_type,
        "warnings": [issue.title for issue in report.issues if issue.severity != "info"],
        "top_recommendations": [
            recommendation.model_dump(mode="json") for recommendation in report.recommendations[:5]
        ],
    }


def site_item(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "site",
        "url": report["requested_url"],
        "seo_score": report["score"]["overall"],
        "seo_grade": report["score"]["grade"],
        "pages_audited": report["sample"]["pages_audited"],
    } | report


def error_item(url: str, code: str, message: str) -> dict[str, Any]:
    return {"type": "error", "url": url, "error": {"code": code, "message": message}}


async def run_audit(actor_input: ActorInput, analyzer: RecordingAnalyzer, sink: Sink) -> RunSummary:
    summary = RunSummary()
    if actor_input.mode == "site":
        crawler = SiteCrawler(analyzer)
        for url in actor_input.urls:
            if not await _audit_site(url, actor_input, analyzer, crawler, sink, summary):
                break
    else:
        await _audit_pages(actor_input, analyzer, sink, summary)
    return summary


async def _audit_pages(
    actor_input: ActorInput, analyzer: Analyzer, sink: Sink, summary: RunSummary
) -> None:
    quick = actor_input.mode == "quick"
    event = QUICK_EVENT if quick else PAGE_EVENT
    pending = list(actor_input.urls)
    while pending:
        affordable = sink.affordable(event)
        size = BATCH_SIZE if affordable is None else min(BATCH_SIZE, affordable)
        if size < 1:
            summary.stopped_by_budget = True
            return
        batch, pending = pending[:size], pending[size:]
        results = await asyncio.gather(
            *(_analyze(analyzer, url, actor_input.include_subdomains) for url in batch)
        )
        for url, result in zip(batch, results, strict=True):
            if isinstance(result, FetchError):
                await sink.push([error_item(url, result.code, result.message)], None)
                summary.failed += 1
            else:
                await sink.push([quick_item(result) if quick else page_item(result)], event)
                summary.audited += 1


async def _analyze(
    analyzer: Analyzer, url: str, include_subdomains: bool
) -> PageAnalysis | FetchError:
    try:
        return await analyzer.analyze(url, include_subdomains=include_subdomains)
    except FetchError as exc:
        return exc
    except Exception as exc:
        return FetchError("unexpected_error", str(exc), status_code=500)


async def _audit_site(
    url: str,
    actor_input: ActorInput,
    analyzer: RecordingAnalyzer,
    crawler: SiteCrawler,
    sink: Sink,
    summary: RunSummary,
) -> bool:
    affordable = sink.affordable(PAGE_EVENT)
    max_pages = (
        actor_input.max_pages if affordable is None else min(actor_input.max_pages, affordable)
    )
    if max_pages < 1:
        summary.stopped_by_budget = True
        return False
    analyzer.reports.clear()
    try:
        report = await crawler.audit(
            SiteAuditRequest(
                url=url,
                max_pages=max_pages,
                max_depth=actor_input.max_depth,
                respect_robots=actor_input.respect_robots,
                include_subdomains=actor_input.include_subdomains,
                use_sitemap=actor_input.use_sitemap,
            )
        )
    except FetchError as exc:
        await sink.push([error_item(url, exc.code, exc.message)], None)
        summary.failed += 1
        return True
    except ValidationError as exc:
        await sink.push([error_item(url, "invalid_url", exc.errors()[0]["msg"])], None)
        summary.failed += 1
        return True
    pages = [page_item(analyzer.reports[row["url"]], crawl=row) for row in report["pages"]]
    await sink.push(pages, PAGE_EVENT)
    await sink.push([site_item(report)], None)
    summary.audited += len(pages)
    if max_pages < actor_input.max_pages and report["sample"]["page_budget_reached"]:
        summary.stopped_by_budget = True
    return True
