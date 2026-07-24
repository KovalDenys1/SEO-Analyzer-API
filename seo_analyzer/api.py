import asyncio
import hmac
import logging
import re
import time
import uuid
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Histogram, generate_latest
from prometheus_client import Counter as PrometheusCounter
from pydantic import ValidationError
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from seo_analyzer import __version__
from seo_analyzer.analyzer import Analyzer
from seo_analyzer.config import Settings, get_settings
from seo_analyzer.crawler import SiteCrawler
from seo_analyzer.fetcher import FetchError
from seo_analyzer.models import CompareRequest, OpportunityRequest, PageAnalysis, SiteAuditRequest
from seo_analyzer.opportunity import rank_opportunities
from seo_analyzer.utils import utc_now_iso

LOGGER = logging.getLogger("seo_analyzer.api")
REQUESTS = PrometheusCounter(
    "seo_analyzer_http_requests_total", "HTTP requests", ("method", "route", "status")
)
REQUEST_SECONDS = Histogram(
    "seo_analyzer_http_request_duration_seconds", "HTTP request duration", ("method", "route")
)
SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
MAX_REQUEST_BODY_BYTES = 1_000_000


class RequestBodyTooLargeError(HTTPException):
    def __init__(self) -> None:
        super().__init__(status_code=413, detail="Request bodies are limited to 1 MB")


class RequestBodyLimitMiddleware:
    """Enforce the body budget for both Content-Length and chunked requests."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        declared_length = headers.get(b"content-length", b"")
        if declared_length.isdigit() and int(declared_length) > self.max_bytes:
            await self._reject(scope, receive, send)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise RequestBodyTooLargeError
            return message

        try:
            await self.app(scope, limited_receive, send)
        except RequestBodyTooLargeError:
            await self._reject(scope, receive, send)

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send) -> None:
        request_id = scope.get("state", {}).get("request_id")
        response = JSONResponse(
            status_code=413,
            content={
                "error": {
                    "code": "request_too_large",
                    "message": "Request bodies are limited to 1 MB",
                    "request_id": request_id,
                }
            },
        )
        await response(scope, receive, send)


def create_app(settings: Settings | None = None, analyzer: Analyzer | None = None) -> FastAPI:
    runtime_settings = settings or get_settings()
    owns_analyzer = analyzer is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logging.basicConfig(
            level=getattr(logging, runtime_settings.log_level.upper(), logging.INFO),
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
        app.state.settings = runtime_settings
        app.state.analyzer = analyzer or Analyzer(runtime_settings)
        app.state.crawler = SiteCrawler(app.state.analyzer)
        yield
        if owns_analyzer:
            await app.state.analyzer.close()

    app = FastAPI(
        title="SaaS SEO Analyzer API",
        summary="Security-first technical SEO, SaaS strategy, crawl, comparison, and opportunity diagnostics",
        description=(
            "Audits public web pages without claiming to predict rankings. Core SEO health and SaaS "
            "acquisition/conversion maturity are scored separately with evidence and prioritized fixes."
        ),
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_tags=[
            {"name": "analysis", "description": "Page and site SEO diagnostics"},
            {"name": "strategy", "description": "Comparison and first-party opportunity ranking"},
            {"name": "compatibility", "description": "Backwards-compatible v1 endpoints"},
            {"name": "operations", "description": "Health and observability"},
        ],
    )
    if runtime_settings.parsed_cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=runtime_settings.parsed_cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "X-API-Key", "X-Request-ID"],
        )
    app.add_middleware(RequestBodyLimitMiddleware, max_bytes=MAX_REQUEST_BODY_BYTES)

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        supplied_request_id = request.headers.get("x-request-id", "")
        request_id = (
            supplied_request_id
            if SAFE_REQUEST_ID.fullmatch(supplied_request_id)
            else str(uuid.uuid4())
        )
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - started
        route = request.scope.get("route")
        route_path = getattr(route, "path", "unmatched")
        REQUESTS.labels(request.method, route_path, response.status_code).inc()
        REQUEST_SECONDS.labels(request.method, route_path).observe(elapsed)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        LOGGER.info(
            "request method=%s route=%s status=%s duration_ms=%s request_id=%s",
            request.method,
            route_path,
            response.status_code,
            round(elapsed * 1_000),
            request_id,
        )
        return response

    @app.exception_handler(FetchError)
    async def fetch_error_handler(request: Request, exc: FetchError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )

    @app.exception_handler(RequestBodyTooLargeError)
    async def body_limit_error_handler(
        request: Request, _exc: RequestBodyTooLargeError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=413,
            content={
                "error": {
                    "code": "request_too_large",
                    "message": "Request bodies are limited to 1 MB",
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )

    async def require_api_key(
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    ) -> None:
        expected = runtime_settings.api_key
        if expected is None or not expected.get_secret_value():
            return
        supplied = x_api_key or ""
        if not hmac.compare_digest(supplied, expected.get_secret_value()):
            raise FetchError("unauthorized", "A valid X-API-Key is required", status_code=401)

    def get_analyzer(request: Request) -> Analyzer:
        return request.app.state.analyzer

    def get_crawler(request: Request) -> SiteCrawler:
        return request.app.state.crawler

    @app.get("/", tags=["operations"])
    async def root() -> dict[str, Any]:
        return {
            "name": "SaaS SEO Analyzer API",
            "version": __version__,
            "status": "ok",
            "documentation": "/docs",
            "endpoints": {
                "page_analysis": "GET /v1/analyze?url=https://example.com",
                "site_audit": "POST /v1/site-audit",
                "comparison": "POST /v1/compare",
                "opportunity_ranking": "POST /v1/opportunities",
            },
        }

    @app.get("/healthz", tags=["operations"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__, "time": utc_now_iso()}

    @app.get("/readyz", tags=["operations"])
    async def ready(current: Analyzer = Depends(get_analyzer)) -> dict[str, Any]:
        return {"status": "ready", "cache_entries": await current.cache.size()}

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get(
        "/v1/analyze",
        tags=["analysis"],
        dependencies=[Depends(require_api_key)],
        response_model=PageAnalysis,
    )
    async def analyze_v1(
        url: str = Query(min_length=4, max_length=2_048),
        include_pagespeed: bool = Query(default=False),
        include_subdomains: bool = Query(default=False),
        current: Analyzer = Depends(get_analyzer),
    ) -> PageAnalysis:
        report = await current.analyze(
            url,
            include_pagespeed=include_pagespeed,
            include_subdomains=include_subdomains,
        )
        return report

    @app.post("/v1/site-audit", tags=["analysis"], dependencies=[Depends(require_api_key)])
    async def site_audit(
        payload: SiteAuditRequest,
        crawler: SiteCrawler = Depends(get_crawler),
    ) -> dict[str, Any]:
        return await crawler.audit(payload)

    @app.post("/v1/compare", tags=["strategy"], dependencies=[Depends(require_api_key)])
    async def compare(
        payload: CompareRequest,
        current: Analyzer = Depends(get_analyzer),
    ) -> dict[str, Any]:
        async def analyze_one(url: str) -> tuple[str, Any]:
            try:
                report = await current.analyze(url, include_pagespeed=payload.include_pagespeed)
                return "ok", report
            except FetchError as exc:
                return "error", {"url": url, "code": exc.code, "error": exc.message}

        results = await asyncio.gather(*(analyze_one(url) for url in payload.urls))
        reports = [value for status, value in results if status == "ok"]
        errors = [value for status, value in results if status == "error"]
        if len(reports) < 2:
            raise FetchError(
                "insufficient_comparable_pages",
                "At least two URLs must be fetched successfully",
                status_code=422,
            )
        seo_ranking = sorted(reports, key=lambda report: -report.score.overall)
        saas_ranking = sorted(
            (report for report in reports if report.saas["score"]["overall"] is not None),
            key=lambda report: -report.saas["score"]["overall"],
        )
        issue_frequency = Counter(issue.code for report in reports for issue in report.issues)
        category_leaders = {}
        for category in reports[0].score.categories:
            leader = max(reports, key=lambda report: report.score.categories[category])
            category_leaders[category] = {
                "url": leader.final_url,
                "score": leader.score.categories[category],
            }
        return {
            "schema_version": "2.0",
            "compared_at": utc_now_iso(),
            "rankings": {
                "seo_health": [
                    {
                        "rank": index,
                        "url": report.final_url,
                        "score": report.score.overall,
                        "grade": report.score.grade,
                    }
                    for index, report in enumerate(seo_ranking, 1)
                ],
                "saas_conversion_readiness": [
                    {
                        "rank": index,
                        "url": report.final_url,
                        "score": report.saas["score"]["overall"],
                        "grade": report.saas["score"]["grade"],
                    }
                    for index, report in enumerate(saas_ranking, 1)
                ],
                "category_leaders": category_leaders,
                "note": "Relative page diagnostics only; this is not a SERP or market-share ranking.",
            },
            "common_gaps": [
                {"issue_code": code, "pages": count}
                for code, count in issue_frequency.most_common()
                if count >= 2
            ],
            "analyses": [report.model_dump(mode="json") for report in reports],
            "errors": errors,
        }

    @app.post("/v1/opportunities", tags=["strategy"], dependencies=[Depends(require_api_key)])
    async def opportunities(payload: OpportunityRequest) -> dict[str, Any]:
        return rank_opportunities(payload)

    @app.get("/analyze", tags=["compatibility"], dependencies=[Depends(require_api_key)])
    async def legacy_analyze(
        url: str = Query(min_length=4, max_length=2_048),
        current: Analyzer = Depends(get_analyzer),
    ) -> dict[str, Any]:
        report = await current.analyze(url)
        return _legacy_payload(report)

    @app.get("/quick-score", tags=["compatibility"], dependencies=[Depends(require_api_key)])
    async def legacy_quick_score(
        url: str = Query(min_length=4, max_length=2_048),
        current: Analyzer = Depends(get_analyzer),
    ) -> dict[str, Any]:
        report = await current.analyze(url)
        return {
            "url": report.final_url,
            "seo_score": report.score.overall,
            "seo_grade": report.score.grade,
            "seo_warnings": [issue.title for issue in report.issues if issue.severity != "info"],
            "top_recommendations": [
                recommendation.model_dump(mode="json")
                for recommendation in report.recommendations[:5]
            ],
        }

    @app.get("/metadata", tags=["compatibility"], dependencies=[Depends(require_api_key)])
    async def legacy_metadata(
        url: str = Query(min_length=4, max_length=2_048),
        current: Analyzer = Depends(get_analyzer),
    ) -> dict[str, Any]:
        report = await current.analyze(url)
        return {
            "url": report.final_url,
            "title": report.metadata["title"],
            "meta": {
                "description": report.metadata["description"],
                "keywords": report.metadata["keywords"],
                "canonical": report.metadata["canonical"],
                "robots": report.indexability["robots_meta"],
            },
            "headings": report.headings,
            "social": report.social,
        }

    return app


def _legacy_payload(report: Any) -> dict[str, Any]:
    h1 = [item["text"] for item in report.headings["items"] if item["level"] == 1]
    h2 = [item["text"] for item in report.headings["items"] if item["level"] == 2]
    return {
        "url": report.final_url,
        "title": report.metadata["title"],
        "meta": {
            "description": report.metadata["description"],
            "keywords": report.metadata["keywords"],
        },
        "headings": {
            "h1": {"count": len(h1), "texts": h1},
            "h2": {"count": len(h2), "texts": h2},
        },
        "links": {
            "internal": [item["url"] for item in report.links["internal"]["items"]],
            "external": [item["url"] for item in report.links["external"]["items"]],
        },
        "images": {
            "total": report.images["total"],
            "with_alt": report.images["with_descriptive_alt"],
            "without_alt": report.images["missing_alt_attribute"],
        },
        "word_count": report.content["word_count"],
        "word_density_percent": {
            item["term"]: item["density_percent"] for item in report.content["top_terms"]
        },
        "load_time_ms": report.fetch["timing"]["total_ms"],
        "seo_warnings": [issue.title for issue in report.issues if issue.severity != "info"],
        "seo_score": report.score.overall,
        "seo_grade": report.score.grade,
        "v2": report.model_dump(mode="json"),
    }


try:
    app = create_app()
except ValidationError as exc:  # pragma: no cover - fail-fast deployment configuration
    raise RuntimeError(f"Invalid SEO Analyzer configuration: {exc}") from exc
