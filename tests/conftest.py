from collections.abc import Awaitable, Callable

import httpx
import pytest

from seo_analyzer.config import Settings
from seo_analyzer.fetcher import IPAddress, SafeFetcher

PUBLIC_IP = "93.184.216.34"


OPTIMIZED_HTML = b"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Acme Workflow Automation Software for Revenue Teams</title>
  <meta name="description" content="Automate repetitive revenue workflows with Acme. Connect your tools, prove outcomes, and start a free workspace today.">
  <link rel="canonical" href="https://saas.test/">
  <link rel="icon" href="/favicon.ico">
  <link rel="alternate" hreflang="en" href="https://saas.test/">
  <link rel="alternate" hreflang="x-default" href="https://saas.test/">
  <meta property="og:title" content="Acme Workflow Automation">
  <meta property="og:description" content="Automate repetitive revenue workflows.">
  <meta property="og:image" content="https://saas.test/product.png">
  <meta property="og:url" content="https://saas.test/">
  <meta name="twitter:card" content="summary_large_image">
  <script type="application/ld+json">
  {"@context":"https://schema.org","@graph":[
    {"@type":"Organization","name":"Acme"},
    {"@type":"SoftwareApplication","name":"Acme","applicationCategory":"BusinessApplication",
     "operatingSystem":"Web","offers":{"@type":"Offer","price":"0"},
     "aggregateRating":{"@type":"AggregateRating","ratingValue":"4.8","ratingCount":"250"}}
  ]}
  </script>
</head>
<body>
  <header><nav>
    <a href="/features">Workflow automation features</a>
    <a href="/pricing">Transparent pricing plans</a>
    <a href="/docs">Developer documentation</a>
    <a href="/customers">Customer stories</a>
  </nav></header>
  <main>
    <h1>Automate repetitive revenue work and save your team time</h1>
    <p>Acme connects the tools that sales and marketing teams already use. Build reliable workflows without maintaining custom scripts, keep every handoff visible, and give operators control over each automated step.</p>
    <p>Teams use the product to route qualified leads, enrich account records, notify owners, and measure completed work. Every workflow includes an audit trail, role controls, retry handling, and clear data checkpoints.</p>
    <h2>See the real product before you commit</h2>
    <img src="/product.png" alt="Acme workflow dashboard showing a lead routing automation" width="1200" height="675">
    <p>Start with a free workspace and a guided template. Connect one workflow, verify the output, and expand only after the team sees a measurable result. No credit card is required and you can cancel anytime.</p>
    <h2>Trusted by secure revenue teams</h2>
    <p>Customer stories document faster lead response and fewer manual errors. Acme is SOC 2 compliant, uses encryption in transit and at rest, and supports enterprise-grade access controls.</p>
    <a href="/signup">Start free</a>
    <a href="/demo">Book a demo</a>
    <a href="https://example.org/research" rel="nofollow">Independent workflow research</a>
  </main>
  <footer><a href="/security">Security and compliance</a></footer>
</body>
</html>"""


POOR_HTML = b"""<html><head><title>X</title><meta name="description" content=""></head>
<body><h3></h3><a href="/target"></a><a href="/one">Learn more</a>
<a href="/two">Learn more</a><a href="/three">Learn more</a>
<a href="/image"><img src="/hero.png"></a><img src="/other.png">
<script type="application/ld+json">{broken</script></body></html>"""


async def public_resolver(_hostname: str, _port: int) -> list[IPAddress]:
    import ipaddress

    return [ipaddress.ip_address(PUBLIC_IP)]


def make_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "cache_ttl_seconds": 0,
        "max_response_bytes": 500_000,
        "fetch_timeout_seconds": 3,
        "max_concurrent_fetches": 4,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def make_fetcher(
    handler: Callable[[httpx.Request], httpx.Response | Awaitable[httpx.Response]],
    *,
    settings: Settings | None = None,
    resolver: Callable[[str, int], Awaitable[list[IPAddress]]] = public_resolver,
) -> SafeFetcher:
    return SafeFetcher(
        settings or make_settings(),
        transport=httpx.MockTransport(handler),
        resolver=resolver,
    )


@pytest.fixture
def optimized_html() -> bytes:
    return OPTIMIZED_HTML


@pytest.fixture
def poor_html() -> bytes:
    return POOR_HTML
