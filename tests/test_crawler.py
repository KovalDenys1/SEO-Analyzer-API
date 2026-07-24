import gzip

import httpx
import pytest
from conftest import OPTIMIZED_HTML, make_fetcher, make_settings

from seo_analyzer.analyzer import Analyzer
from seo_analyzer.crawler import SiteCrawler
from seo_analyzer.models import SiteAuditRequest


def page_html(title: str, *, canonical: str, body: str = "") -> bytes:
    words = " ".join(["useful workflow evidence for revenue teams"] * 35)
    return f"""<!doctype html><html lang='en'><head><meta charset='utf-8'>
    <meta name='viewport' content='width=device-width'><title>{title}</title>
    <meta name='description' content='A unique and useful description for {title}.'>
    <link rel='canonical' href='{canonical}'></head><body>
    <main><h1>{title}</h1><p>{words}</p>{body}
    <a href='/pricing'>Pricing plans for revenue teams</a></main></body></html>""".encode()


class SiteHandler:
    def __init__(self, *, robots_status: int = 200) -> None:
        self.robots_status = robots_status
        root = OPTIMIZED_HTML.replace(b"saas.test", b"site.test")
        self.root = root.replace(b"</main>", b"<a href='/broken'>Broken target</a></main>")

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/robots.txt":
            if self.robots_status != 200:
                return httpx.Response(self.robots_status, text="server error")
            return httpx.Response(
                200,
                headers={"content-type": "text/plain"},
                text=(
                    "User-agent: *\nDisallow: /blocked\nCrawl-delay: 1\n"
                    "Sitemap: https://site.test/sitemap.xml\n"
                ),
            )
        if path == "/sitemap.xml":
            return httpx.Response(
                200,
                headers={"content-type": "application/xml"},
                text="""<?xml version='1.0'?><urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>
                <url><loc>https://site.test/pricing</loc></url>
                <url><loc>https://site.test/features</loc></url>
                <url><loc>https://site.test/duplicate-a</loc></url>
                <url><loc>https://site.test/duplicate-b</loc></url>
                <url><loc>https://site.test/orphan</loc></url>
                <url><loc>https://site.test/blocked</loc></url>
                </urlset>""",
            )
        if path == "/":
            return httpx.Response(
                200,
                headers={"content-type": "text/html", "content-encoding": "br"},
                content=self.root,
            )
        if path == "/broken":
            return httpx.Response(
                404,
                headers={"content-type": "text/html"},
                content=page_html("Missing workflow page", canonical="https://site.test/broken"),
            )
        if path in {"/duplicate-a", "/duplicate-b"}:
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=page_html(
                    "Duplicate workflow landing page",
                    canonical=f"https://site.test{path}",
                    body="<p>Identical body copy for this test.</p>",
                ),
            )
        if path == "/bad-json":
            return httpx.Response(
                200, headers={"content-type": "application/json"}, json={"bad": True}
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=page_html(
                f"Useful {path.strip('/') or 'home'} software page",
                canonical=f"https://site.test{path}",
            ),
        )


@pytest.mark.asyncio
async def test_site_crawl_respects_robots_and_builds_rankings() -> None:
    settings = make_settings(cache_ttl_seconds=60, max_site_pages=50)
    fetcher = make_fetcher(SiteHandler(), settings=settings)
    analyzer = Analyzer(settings, fetcher=fetcher)
    try:
        report = await SiteCrawler(analyzer).audit(
            SiteAuditRequest(
                url="https://site.test",
                max_pages=20,
                max_depth=3,
                concurrency=4,
            )
        )
    finally:
        await analyzer.close()
    assert report["sample"]["pages_audited"] >= 10
    assert report["sample"]["blocked_by_robots"] == 1
    assert "https://site.test/blocked" in report["robots_blocked_urls"]
    assert report["technical_assets"]["robots"]["state"] == "available"
    assert report["technical_assets"]["robots"]["crawl_delay_seconds"] == 1
    assert report["technical_assets"]["sitemap"]["url_count"] == 6
    assert len(report["technical_assets"]["sitemap"]["url_samples"]) == 6
    assert report["architecture"]["broken_pages"] == ["https://site.test/broken"]
    assert any(
        edge["target"] == "https://site.test/broken"
        for edge in report["architecture"]["broken_internal_edges"]
    )
    assert "https://site.test/orphan" in report["architecture"]["orphan_candidates"]
    assert report["duplicates"]["titles"][0]["count"] == 2
    assert report["duplicates"]["exact_content_signatures"][0]["count"] >= 2
    assert report["rankings"]["seo_health"]
    assert report["rankings"]["optimization_opportunity"]
    assert report["saas_strategy"]["pillars"]
    assert report["recommendations"] == sorted(
        report["recommendations"], key=lambda item: (-item["priority"], item["code"])
    )


@pytest.mark.asyncio
async def test_robots_server_failure_stops_respectful_crawl() -> None:
    settings = make_settings()
    fetcher = make_fetcher(SiteHandler(robots_status=503), settings=settings)
    analyzer = Analyzer(settings, fetcher=fetcher)
    try:
        report = await SiteCrawler(analyzer).audit(
            SiteAuditRequest(url="https://site.test", max_pages=5, respect_robots=True)
        )
    finally:
        await analyzer.close()
    assert report["technical_assets"]["robots"]["state"] == "temporarily_unreachable"
    assert report["technical_assets"]["sitemap"]["state"] == ("skipped_robots_unreachable")
    assert report["sample"]["pages_audited"] == 0
    assert report["sample"]["blocked_by_robots"] >= 1
    assert report["score"]["overall"] is None
    assert report["score"]["rating"] == "not_available"


@pytest.mark.asyncio
async def test_robots_can_be_ignored_explicitly() -> None:
    settings = make_settings()
    fetcher = make_fetcher(SiteHandler(robots_status=503), settings=settings)
    analyzer = Analyzer(settings, fetcher=fetcher)
    try:
        report = await SiteCrawler(analyzer).audit(
            SiteAuditRequest(
                url="https://site.test", max_pages=1, respect_robots=False, use_sitemap=False
            )
        )
    finally:
        await analyzer.close()
    assert report["sample"]["pages_audited"] == 1
    assert report["technical_assets"]["sitemap"]["state"] == "not_requested"


@pytest.mark.asyncio
async def test_sitemap_index_and_gzip_child() -> None:
    child_xml = b"""<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>
    <url><loc>https://site.test/pricing</loc></url>
    <url><loc>https://other.test/cross-site</loc></url></urlset>"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200,
                headers={"content-type": "text/plain"},
                text="Sitemap: https://site.test/index.xml\n",
            )
        if request.url.path == "/index.xml":
            return httpx.Response(
                200,
                headers={"content-type": "application/xml"},
                text="""<sitemapindex xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>
                <sitemap><loc>https://site.test/child.xml.gz</loc></sitemap></sitemapindex>""",
            )
        if request.url.path == "/child.xml.gz":
            return httpx.Response(
                200,
                headers={"content-type": "application/gzip"},
                content=gzip.compress(child_xml),
            )
        return httpx.Response(404)

    settings = make_settings()
    fetcher = make_fetcher(handler, settings=settings)
    analyzer = Analyzer(settings, fetcher=fetcher)
    crawler = SiteCrawler(analyzer)
    try:
        robots = await crawler._fetch_robots("https://site.test")
        sitemap = await crawler._discover_sitemaps(
            "https://site.test", robots, include_subdomains=False
        )
    finally:
        await analyzer.close()
    assert sitemap["state"] == "available"
    assert len(sitemap["documents"]) == 2
    assert sitemap["urls"] == ["https://site.test/pricing"]


@pytest.mark.asyncio
async def test_malformed_sitemap_and_fetch_failures_are_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200,
                headers={"content-type": "text/plain"},
                text="Sitemap: https://site.test/sitemap.xml\n",
            )
        if request.url.path == "/sitemap.xml":
            return httpx.Response(200, headers={"content-type": "application/xml"}, text="<broken")
        if request.url.path == "/":
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=b"<html><body><a href='/bad-json'>Bad</a></body></html>",
            )
        return httpx.Response(200, headers={"content-type": "application/json"}, json={"bad": True})

    settings = make_settings()
    fetcher = make_fetcher(handler, settings=settings)
    analyzer = Analyzer(settings, fetcher=fetcher)
    try:
        report = await SiteCrawler(analyzer).audit(
            SiteAuditRequest(url="https://site.test", max_pages=3)
        )
    finally:
        await analyzer.close()
    assert report["technical_assets"]["sitemap"]["state"] == "error"
    assert report["technical_assets"]["sitemap"]["errors"]
    assert report["crawl_errors"][0]["code"] == "unsupported_content_type"


@pytest.mark.asyncio
async def test_failures_consume_crawl_budget_and_server_cap_is_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404, headers={"content-type": "text/plain"})
        if request.url.path == "/":
            links = "".join(f"<a href='/bad-{index}'>Bad</a>" for index in range(30))
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text=f"<html><body>{links}</body></html>",
            )
        return httpx.Response(200, headers={"content-type": "application/json"}, json={})

    settings = make_settings(max_site_pages=4)
    analyzer = Analyzer(settings, fetcher=make_fetcher(handler, settings=settings))
    try:
        report = await SiteCrawler(analyzer).audit(
            SiteAuditRequest(url="https://site.test", max_pages=20, use_sitemap=False)
        )
    finally:
        await analyzer.close()
    assert report["sample"]["requested_max_pages"] == 20
    assert report["sample"]["max_pages"] == 4
    assert report["sample"]["urls_processed"] == 4
    assert report["sample"]["fetch_attempts"] == 4
    assert report["sample"]["page_budget_reached"] is True
    assert report["sample"]["truncated"] is True


@pytest.mark.asyncio
async def test_invalid_and_cross_site_sitemap_locations_are_safe() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200,
                headers={"content-type": "text/plain"},
                text="Sitemap: https://site.test:bad/sitemap.xml\n",
            )
        if request.url.path == "/sitemap.xml":
            if request.headers["host"] == "other.test":
                return httpx.Response(
                    200,
                    headers={"content-type": "application/xml"},
                    text="<urlset/>",
                )
            return httpx.Response(
                302,
                headers={"location": "https://other.test/sitemap.xml"},
            )
        return httpx.Response(
            200,
            headers={"content-type": "application/xml"},
            text="<urlset/>",
        )

    settings = make_settings()
    analyzer = Analyzer(settings, fetcher=make_fetcher(handler, settings=settings))
    crawler = SiteCrawler(analyzer)
    try:
        robots = await crawler._fetch_robots("https://site.test")
        assert robots.sitemap_urls == []
        sitemap = await crawler._discover_sitemaps(
            "https://site.test", robots, include_subdomains=False
        )
    finally:
        await analyzer.close()
    assert sitemap["state"] == "error"
    assert "cross-site" in sitemap["errors"][0]["error"]
