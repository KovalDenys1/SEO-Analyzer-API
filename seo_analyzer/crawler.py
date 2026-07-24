import asyncio
import gzip
import io
import re
import urllib.robotparser
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

from defusedxml import ElementTree

from seo_analyzer.analyzer import AnalysisArtifact, Analyzer
from seo_analyzer.fetcher import FetchError, SafeFetcher
from seo_analyzer.models import PageType, Severity, SiteAuditRequest
from seo_analyzer.saas import assess_site_strategy, classify_path
from seo_analyzer.utils import grade_for, normalize_url, origin_for, same_site, utc_now_iso


@dataclass(slots=True)
class RobotsSnapshot:
    url: str
    status_code: int | None
    state: str
    text: str = ""
    sitemap_urls: list[str] = field(default_factory=list)
    crawl_delay_seconds: float | None = None
    error: str | None = None
    parser: urllib.robotparser.RobotFileParser | None = None

    def can_fetch(self, user_agent: str, url: str) -> bool:
        if self.state in {"temporarily_unreachable", "fetch_error"}:
            return False
        if self.parser is None:
            return True
        return self.parser.can_fetch(user_agent, url)

    def public_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "status_code": self.status_code,
            "state": self.state,
            "sitemaps": self.sitemap_urls,
            "crawl_delay_seconds": self.crawl_delay_seconds,
            "crawl_delay_note": "crawl-delay is recorded but is not part of RFC 9309; keep crawl concurrency low when a site declares it.",
            "error": self.error,
        }


@dataclass(slots=True)
class CrawlRecord:
    artifact: AnalysisArtifact
    depth: int | None
    source: str


class SiteCrawler:
    def __init__(self, analyzer: Analyzer) -> None:
        self.analyzer = analyzer
        self.fetcher: SafeFetcher = analyzer.fetcher

    async def audit(self, request: SiteAuditRequest) -> dict[str, Any]:
        parsed_start, _ = await self.fetcher.validate(request.url)
        start_url = normalize_url(str(parsed_start), keep_query=request.include_query_parameters)
        origin = origin_for(start_url)
        root_url = f"{origin}/"
        robots = await self._fetch_robots(origin)
        if request.use_sitemap and not (
            request.respect_robots and robots.state in {"temporarily_unreachable", "fetch_error"}
        ):
            sitemap = await self._discover_sitemaps(origin, robots, request.include_subdomains)
        elif request.use_sitemap:
            sitemap = {
                "state": "skipped_robots_unreachable",
                "documents": [],
                "urls": [],
                "url_count": 0,
                "errors": [],
                "truncated": False,
            }
        else:
            sitemap = {
                "state": "not_requested",
                "documents": [],
                "urls": [],
                "url_count": 0,
                "errors": [],
                "truncated": False,
            }

        max_pages = min(request.max_pages, self.analyzer.settings.max_site_pages)
        queue: deque[tuple[str, int | None, str]] = deque()
        queued: set[str] = set()
        crawled: dict[str, CrawlRecord] = {}
        failures: list[dict[str, Any]] = []
        blocked: list[str] = []
        out_of_scope_redirects: list[dict[str, str]] = []
        discovered: set[str] = set(sitemap["urls"])
        inlinks: Counter[str] = Counter()
        source_links: dict[str, list[str]] = {}

        def enqueue(url: str, depth: int | None, source: str, *, front: bool = False) -> None:
            try:
                normalized = normalize_url(url, keep_query=request.include_query_parameters)
            except (ValueError, UnicodeError):
                return
            if not same_site(normalized, start_url, include_subdomains=request.include_subdomains):
                return
            discovered.add(normalized)
            if normalized in queued or normalized in crawled:
                return
            queued.add(normalized)
            item = (normalized, depth, source)
            queue.appendleft(item) if front else queue.append(item)

        enqueue(start_url, 0, "requested")
        if root_url != start_url:
            enqueue(root_url, 0, "site_root")

        strategy_seeds = self._strategic_sitemap_sample(
            list(sitemap.get("urls", [])), max_pages * 3
        )
        seeds_added = False
        processed_urls = 0
        semaphore = asyncio.Semaphore(request.concurrency)

        async def crawl_one(url: str, depth: int | None, source: str) -> tuple[str, Any]:
            if request.respect_robots and not robots.can_fetch(
                self.analyzer.settings.robots_user_agent, url
            ):
                return "blocked", {"url": url, "depth": depth, "source": source}
            async with semaphore:
                try:
                    artifact = await self.analyzer.analyze_artifact(
                        url, include_subdomains=request.include_subdomains
                    )
                    if not same_site(
                        artifact.report.final_url,
                        start_url,
                        include_subdomains=request.include_subdomains,
                    ):
                        return "out_of_scope", {
                            "source": url,
                            "target": artifact.report.final_url,
                        }
                    return "ok", CrawlRecord(artifact=artifact, depth=depth, source=source)
                except FetchError as exc:
                    return "error", {
                        "url": url,
                        "depth": depth,
                        "source": source,
                        "code": exc.code,
                        "error": exc.message,
                        "status_code": exc.status_code,
                    }
                except Exception as exc:  # pragma: no cover - final isolation boundary
                    return "error", {
                        "url": url,
                        "depth": depth,
                        "source": source,
                        "code": "unexpected_error",
                        "error": str(exc),
                    }

        while queue and processed_urls < max_pages:
            batch: list[tuple[str, int | None, str]] = []
            while (
                queue
                and len(batch) < request.concurrency
                and processed_urls + len(batch) < max_pages
            ):
                batch.append(queue.popleft())
            processed_urls += len(batch)
            results = await asyncio.gather(*(crawl_one(*item) for item in batch))
            newly_discovered: list[tuple[str, int, str]] = []
            for (url, depth, _source), (status, payload) in zip(batch, results, strict=True):
                if status == "blocked":
                    blocked.append(url)
                    continue
                if status == "error":
                    failures.append(payload)
                    continue
                if status == "out_of_scope":
                    out_of_scope_redirects.append(payload)
                    continue
                record: CrawlRecord = payload
                final_key = normalize_url(
                    record.artifact.report.final_url,
                    keep_query=request.include_query_parameters,
                )
                crawled[final_key] = record
                links = [
                    normalize_url(link, keep_query=request.include_query_parameters)
                    for link in record.artifact.parsed.internal_urls
                    if same_site(link, start_url, include_subdomains=request.include_subdomains)
                ]
                source_links[final_key] = list(dict.fromkeys(links))
                for link in source_links[final_key]:
                    discovered.add(link)
                    inlinks[link] += 1
                    next_depth = (depth + 1) if depth is not None else 1
                    if next_depth <= request.max_depth:
                        newly_discovered.append((link, next_depth, "internal_link"))

            for item in reversed(newly_discovered):
                enqueue(*item, front=True)
            if not seeds_added:
                for seed in strategy_seeds:
                    enqueue(seed, None, "sitemap")
                seeds_added = True

        return self._build_report(
            request=request,
            start_url=start_url,
            origin=origin,
            robots=robots,
            sitemap=sitemap,
            crawled=crawled,
            failures=failures,
            blocked=blocked,
            out_of_scope_redirects=out_of_scope_redirects,
            discovered=discovered,
            inlinks=inlinks,
            source_links=source_links,
            queued_remaining=len(queue),
            processed_urls=processed_urls,
            effective_max_pages=max_pages,
        )

    async def _fetch_robots(self, origin: str) -> RobotsSnapshot:
        url = f"{origin}/robots.txt"
        try:
            result = await self.fetcher.fetch(
                url,
                accepted_content_types=None,
                max_bytes=min(500_000, self.analyzer.settings.max_response_bytes),
            )
        except FetchError as exc:
            return RobotsSnapshot(
                url=url,
                status_code=None,
                state="fetch_error",
                error=f"{exc.code}: {exc.message}",
            )
        if 500 <= result.status_code < 600:
            return RobotsSnapshot(
                url=url,
                status_code=result.status_code,
                state="temporarily_unreachable",
                error="RFC 9309 treats server/network failures conservatively; this audit will not crawl blocked paths.",
            )
        if not 200 <= result.status_code < 300:
            return RobotsSnapshot(
                url=url,
                status_code=result.status_code,
                state="unavailable_allow",
            )
        text = result.text.lstrip("\ufeff")
        parser = urllib.robotparser.RobotFileParser(url)
        parser.parse(text.splitlines())
        sitemap_urls = []
        for line in text.splitlines():
            match = re.match(r"\s*sitemaps?\s*:\s*(\S+)", line, re.IGNORECASE)
            if match:
                try:
                    sitemap_urls.append(normalize_url(urljoin(origin, match.group(1))))
                except (ValueError, UnicodeError):
                    continue
        delay = parser.crawl_delay(self.analyzer.settings.robots_user_agent) or parser.crawl_delay(
            "*"
        )
        return RobotsSnapshot(
            url=url,
            status_code=result.status_code,
            state="available",
            text=text,
            sitemap_urls=list(dict.fromkeys(sitemap_urls)),
            crawl_delay_seconds=float(delay) if delay else None,
            parser=parser,
        )

    async def _discover_sitemaps(
        self, origin: str, robots: RobotsSnapshot, include_subdomains: bool
    ) -> dict[str, Any]:
        pending = deque(robots.sitemap_urls or [f"{origin}/sitemap.xml"])
        seen_documents: set[str] = set()
        documents: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        urls: list[str] = []
        while pending and len(seen_documents) < 12 and len(urls) < 5_000:
            raw_sitemap_url = pending.popleft()
            try:
                sitemap_url = normalize_url(raw_sitemap_url)
            except (ValueError, UnicodeError):
                errors.append(
                    {
                        "url": str(raw_sitemap_url)[:500],
                        "error": "invalid sitemap URL",
                    }
                )
                continue
            if sitemap_url in seen_documents:
                continue
            seen_documents.add(sitemap_url)
            if not same_site(sitemap_url, origin, include_subdomains=include_subdomains):
                errors.append({"url": sitemap_url, "error": "cross-site sitemap skipped"})
                continue
            try:
                result = await self.fetcher.fetch(
                    sitemap_url,
                    accepted_content_types=None,
                    max_bytes=self.analyzer.settings.max_response_bytes,
                )
                if not same_site(result.final_url, origin, include_subdomains=include_subdomains):
                    errors.append(
                        {
                            "url": sitemap_url,
                            "error": f"redirected to cross-site sitemap: {result.final_url}",
                        }
                    )
                    continue
                if not 200 <= result.status_code < 300:
                    errors.append({"url": sitemap_url, "error": f"HTTP {result.status_code}"})
                    continue
                content = result.content
                if content.startswith(b"\x1f\x8b"):
                    decompressed_limit = self.analyzer.settings.max_response_bytes * 4
                    with gzip.GzipFile(fileobj=io.BytesIO(content)) as archive:
                        content = archive.read(decompressed_limit + 1)
                    if len(content) > decompressed_limit:
                        raise ValueError("decompressed sitemap exceeds safety limit")
                root = ElementTree.fromstring(content)
            except (FetchError, ElementTree.ParseError, OSError, ValueError) as exc:
                errors.append({"url": sitemap_url, "error": str(exc)})
                continue
            root_name = root.tag.rsplit("}", 1)[-1].lower()
            locations = [
                (element.text or "").strip()
                for element in root.iter()
                if element.tag.rsplit("}", 1)[-1].lower() == "loc" and element.text
            ]
            documents.append({"url": sitemap_url, "type": root_name, "locations": len(locations)})
            if root_name == "sitemapindex":
                pending.extend(locations[:100])
            elif root_name == "urlset":
                for location in locations:
                    try:
                        normalized = normalize_url(location)
                    except (ValueError, UnicodeError):
                        continue
                    if same_site(normalized, origin, include_subdomains=include_subdomains):
                        urls.append(normalized)
                        if len(urls) >= 5_000:
                            break
            else:
                errors.append({"url": sitemap_url, "error": f"unexpected root: {root_name}"})
        state = "available" if documents else ("error" if errors else "missing")
        return {
            "state": state,
            "documents": documents,
            "urls": list(dict.fromkeys(urls)),
            "url_count": len(set(urls)),
            "errors": errors,
            "truncated": bool(pending) or len(urls) >= 5_000,
        }

    @staticmethod
    def _strategic_sitemap_sample(urls: list[str], limit: int) -> list[str]:
        buckets: dict[PageType, deque[str]] = defaultdict(deque)
        for url in urls:
            buckets[classify_path(url)].append(url)
        priority = [
            PageType.PRICING,
            PageType.FEATURE,
            PageType.USE_CASE,
            PageType.INDUSTRY,
            PageType.INTEGRATION,
            PageType.COMPARISON,
            PageType.ALTERNATIVE,
            PageType.TEMPLATE,
            PageType.FREE_TOOL,
            PageType.CASE_STUDY,
            PageType.SECURITY,
            PageType.DOCS,
            PageType.CHANGELOG,
            PageType.GUIDE,
            PageType.BLOG,
            PageType.OTHER,
        ]
        sample: list[str] = []
        while len(sample) < limit and any(buckets.values()):
            changed = False
            for page_type in priority:
                if buckets[page_type] and len(sample) < limit:
                    sample.append(buckets[page_type].popleft())
                    changed = True
            if not changed:
                break
        return sample

    def _build_report(
        self,
        *,
        request: SiteAuditRequest,
        start_url: str,
        origin: str,
        robots: RobotsSnapshot,
        sitemap: dict[str, Any],
        crawled: dict[str, CrawlRecord],
        failures: list[dict[str, Any]],
        blocked: list[str],
        out_of_scope_redirects: list[dict[str, str]],
        discovered: set[str],
        inlinks: Counter[str],
        source_links: dict[str, list[str]],
        queued_remaining: int,
        processed_urls: int,
        effective_max_pages: int,
    ) -> dict[str, Any]:
        records = list(crawled.items())
        page_weights = {
            PageType.HOME: 2.5,
            PageType.PRICING: 2.2,
            PageType.FEATURE: 1.8,
            PageType.USE_CASE: 1.8,
            PageType.INDUSTRY: 1.8,
            PageType.INTEGRATION: 1.6,
            PageType.COMPARISON: 1.8,
            PageType.ALTERNATIVE: 1.8,
            PageType.FREE_TOOL: 1.6,
        }
        total_weight = (
            sum(page_weights.get(record.artifact.parsed.page_type, 1.0) for _, record in records)
            or 1
        )
        overall = None
        if records:
            overall = round(
                sum(
                    record.artifact.report.score.overall
                    * page_weights.get(record.artifact.parsed.page_type, 1.0)
                    for _, record in records
                )
                / total_weight,
                1,
            )
            grade, rating = grade_for(overall)
        else:
            grade, rating = None, "not_available"
        category_scores: dict[str, float] = {}
        if records:
            for category in records[0][1].artifact.report.score.categories:
                category_scores[category] = round(
                    sum(
                        record.artifact.report.score.categories[category]
                        * page_weights.get(record.artifact.parsed.page_type, 1.0)
                        for _, record in records
                    )
                    / total_weight,
                    1,
                )

        title_groups = _duplicate_groups(
            records, lambda record: record.artifact.parsed.title.strip().lower()
        )
        description_groups = _duplicate_groups(
            records, lambda record: record.artifact.parsed.description.strip().lower()
        )
        content_groups = _duplicate_groups(
            records, lambda record: record.artifact.parsed.text_signature
        )
        broken_pages = [
            url for url, record in records if record.artifact.report.fetch["status_code"] >= 400
        ]
        broken_link_edges = [
            {"source": source, "target": target}
            for source, targets in source_links.items()
            for target in targets
            if target in broken_pages
        ]
        audited_sitemap_urls = set(sitemap["urls"]) & set(crawled)
        orphan_candidates = sorted(
            url
            for url in audited_sitemap_urls
            if inlinks[url] == 0 and normalize_url(url) != normalize_url(start_url)
        )

        severity_order = {
            Severity.CRITICAL.value: 0,
            Severity.HIGH.value: 1,
            Severity.MEDIUM.value: 2,
            Severity.LOW.value: 3,
            Severity.INFO.value: 4,
        }
        issue_map: dict[str, dict[str, Any]] = {}
        for url, record in records:
            for issue in record.artifact.report.issues:
                item = issue_map.setdefault(
                    issue.code,
                    {
                        "code": issue.code,
                        "title": issue.title,
                        "category": issue.category,
                        "severity": issue.severity.value,
                        "count": 0,
                        "urls": [],
                    },
                )
                if severity_order[issue.severity.value] < severity_order[item["severity"]]:
                    item["severity"] = issue.severity.value
                item["count"] += 1
                if len(item["urls"]) < 25:
                    item["urls"].append(url)
        issue_summary = sorted(
            issue_map.values(),
            key=lambda item: (severity_order[item["severity"]], -item["count"], item["code"]),
        )

        recommendations = _aggregate_recommendations(records)
        discovered_page_types = [classify_path(url) for url in discovered]
        strategy = assess_site_strategy(discovered_page_types, len(discovered))
        for pillar_id, pillar in strategy["pillars"].items():
            if pillar["opportunity"]:
                recommendations.append(
                    {
                        "code": f"strategy.{pillar_id}",
                        "priority": 55,
                        "impact": "high",
                        "effort": "high",
                        "confidence": 0.55,
                        "title": f"Validate {pillar['label'].lower()} coverage",
                        "action": pillar["opportunity"],
                        "why": "Successful SaaS sites commonly map distinct user jobs and evaluation stages to useful, internally connected assets.",
                        "validation": "Validate demand and product fit first; publish a small set, measure qualified organic conversions, and expand only where pages remain unique and useful.",
                        "affected_pages": 1,
                        "issue_codes": [],
                    }
                )
        recommendations.sort(key=lambda item: (-item["priority"], item["code"]))

        page_summaries = []
        for url, record in records:
            report = record.artifact.report
            saas_score = report.saas["score"]["overall"]
            importance = page_weights.get(record.artifact.parsed.page_type, 1.0)
            gap = 100 - report.score.overall
            saas_gap = (100 - saas_score) if saas_score is not None else 0
            opportunity = round(min(100, (gap * 0.7 + saas_gap * 0.3) * min(1, importance / 2)))
            page_summaries.append(
                {
                    "url": url,
                    "page_type": record.artifact.parsed.page_type.value,
                    "source": record.source,
                    "depth": record.depth,
                    "status_code": report.fetch["status_code"],
                    "indexable": report.indexability["indexable"],
                    "title": report.metadata["title"],
                    "seo_score": report.score.overall,
                    "seo_grade": report.score.grade,
                    "saas_score": saas_score,
                    "issue_count": len(report.issues),
                    "inlinks_from_sample": inlinks[url],
                    "opportunity_score": opportunity,
                }
            )
        seo_ranking = sorted(page_summaries, key=lambda item: (-item["seo_score"], item["url"]))
        saas_ranking = sorted(
            (item for item in page_summaries if item["saas_score"] is not None),
            key=lambda item: (-item["saas_score"], item["url"]),
        )
        opportunity_ranking = sorted(
            page_summaries,
            key=lambda item: (-item["opportunity_score"], item["seo_score"], item["url"]),
        )
        authority_ranking = sorted(
            page_summaries,
            key=lambda item: (-item["inlinks_from_sample"], item["url"]),
        )

        return {
            "schema_version": "2.0",
            "audited_at": utc_now_iso(),
            "site": origin,
            "requested_url": start_url,
            "score": {
                "overall": overall,
                "grade": grade,
                "rating": rating,
                "categories": category_scores,
                "methodology_version": "2026.1",
                "aggregation": "Page-type-weighted mean over the audited sample",
            },
            "sample": {
                "max_pages": effective_max_pages,
                "requested_max_pages": request.max_pages,
                "pages_audited": len(crawled),
                "urls_processed": processed_urls,
                "fetch_attempts": processed_urls - len(blocked),
                "urls_discovered": len(discovered),
                "sitemap_urls": len(sitemap["urls"]),
                "blocked_by_robots": len(blocked),
                "fetch_failures": len(failures),
                "queue_remaining": queued_remaining,
                "max_depth": request.max_depth,
                "page_budget_reached": processed_urls >= effective_max_pages,
                "truncated": queued_remaining > 0
                or len(discovered) > processed_urls
                or bool(sitemap.get("truncated")),
            },
            "technical_assets": {
                "robots": robots.public_dict(),
                "sitemap": {key: value for key, value in sitemap.items() if key != "urls"}
                | {"url_samples": sitemap["urls"][:100]},
            },
            "saas_strategy": strategy,
            "pages": sorted(page_summaries, key=lambda item: item["url"]),
            "rankings": {
                "seo_health": seo_ranking,
                "saas_conversion_readiness": saas_ranking,
                "optimization_opportunity": opportunity_ranking,
                "internal_authority_in_sample": authority_ranking,
                "note": "These are relative audit rankings, not Google SERP positions. Opportunity scores prioritize sampled gaps and page type, not search volume.",
            },
            "architecture": {
                "broken_internal_edges": broken_link_edges[:100],
                "broken_pages": broken_pages,
                "orphan_candidates": orphan_candidates[:100],
                "orphan_note": "Candidates are sitemap URLs audited with no incoming link in the capped crawl; a full crawl may find additional links.",
                "top_linked_pages": authority_ranking[:20],
            },
            "duplicates": {
                "titles": title_groups,
                "descriptions": description_groups,
                "exact_content_signatures": content_groups,
                "note": "Exact normalized duplicates are high-confidence. Near-duplicate/cannibalization analysis requires deeper semantic and query data.",
            },
            "issues": issue_summary,
            "recommendations": recommendations[:100],
            "crawl_errors": failures[:100],
            "out_of_scope_redirects": out_of_scope_redirects[:100],
            "robots_blocked_urls": blocked[:100],
            "limitations": [
                "This is a bounded sample, not an exhaustive enterprise crawl.",
                "Robots rules are respected by default; blocked pages are not fetched.",
                "Static fetches do not execute JavaScript, submit forms, or measure browser Core Web Vitals.",
                "Strategy coverage inferred from URL patterns proves neither page quality nor organic demand.",
                "Use Search Console and analytics/conversion data to validate traffic and commercial priority.",
            ],
        }


def _duplicate_groups(
    records: list[tuple[str, CrawlRecord]], key_function: Any
) -> list[dict[str, Any]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for url, record in records:
        key = key_function(record)
        if key:
            groups[key].append(url)
    duplicates = [
        {"value": key if len(key) <= 180 else f"{key[:177]}…", "count": len(urls), "urls": urls}
        for key, urls in groups.items()
        if len(urls) > 1
    ]
    return sorted(duplicates, key=lambda item: (-item["count"], item["value"]))


def _aggregate_recommendations(
    records: list[tuple[str, CrawlRecord]],
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for url, record in records:
        for recommendation in record.artifact.report.recommendations:
            item = grouped.get(recommendation.code)
            if item is None:
                item = recommendation.model_dump(mode="json")
                item["urls"] = []
                item["affected_pages"] = 0
                grouped[recommendation.code] = item
            item["affected_pages"] += 1
            if len(item["urls"]) < 25:
                item["urls"].append(url)
            item["priority"] = min(
                100, round(recommendation.priority + min(20, item["affected_pages"] * 2))
            )
    return sorted(grouped.values(), key=lambda item: (-item["priority"], item["code"]))
