import ipaddress
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from src.audit import RecordingAnalyzer

from seo_analyzer.config import Settings
from seo_analyzer.fetcher import IPAddress, SafeFetcher


def _page(title: str, *, description: str | None, body: str) -> bytes:
    meta = f'<meta name="description" content="{description}">' if description else ""
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{title}</title>{meta}</head><body>{body}</body></html>"
    ).encode()


SITE = {
    "/": _page(
        "Acme home",
        description="Acme automates revenue workflows for sales and marketing teams.",
        body=(
            "<h1>Automate revenue work</h1>"
            '<a href="/pricing">Pricing plans</a> <a href="/features">Product features</a>'
        ),
    ),
    "/pricing": _page("Acme pricing", description=None, body="<h1>Pricing</h1>"),
    "/features": _page(
        "Acme features",
        description="Every Acme feature for routing, enrichment and reporting in one list.",
        body="<h1>Features</h1>",
    ),
}


@dataclass
class Ledger:
    """Stands in for the Apify dataset and its charging manager."""

    budget: int | None = None
    items: list[dict[str, Any]] = field(default_factory=list)
    events: list[str | None] = field(default_factory=list)

    def affordable(self, _event: str) -> int | None:
        return self.budget

    async def push(self, items: list[dict[str, Any]], event: str | None) -> None:
        self.items.extend(items)
        self.events.extend([event] * len(items))
        if event is not None and self.budget is not None:
            self.budget -= len(items)


@dataclass
class FakeSite:
    analyzer: RecordingAnalyzer
    fetched_paths: list[str]


async def _public_resolver(_hostname: str, _port: int) -> list[IPAddress]:
    return [ipaddress.ip_address("93.184.216.34")]


@pytest.fixture
async def site() -> Any:
    fetched_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        fetched_paths.append(request.url.path)
        if request.url.path == "/boom":
            raise RuntimeError("socket exploded")
        html = SITE.get(request.url.path)
        if html is None:
            return httpx.Response(404, headers={"content-type": "text/plain"}, content=b"gone")
        return httpx.Response(200, headers={"content-type": "text/html"}, content=html)

    settings = Settings(_env_file=None)
    fetcher = SafeFetcher(
        settings, transport=httpx.MockTransport(handler), resolver=_public_resolver
    )
    analyzer = RecordingAnalyzer(settings, fetcher=fetcher)
    yield FakeSite(analyzer=analyzer, fetched_paths=fetched_paths)
    await analyzer.close()
