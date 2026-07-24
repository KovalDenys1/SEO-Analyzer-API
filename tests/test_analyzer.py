import asyncio

import httpx
import pytest
from conftest import OPTIMIZED_HTML, make_fetcher, make_settings

from seo_analyzer.analyzer import Analyzer
from seo_analyzer.fetcher import FetchError


class FakePageSpeed:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.closed = False

    async def analyze(self, url: str) -> dict:
        self.calls.append(url)
        return {"status": "complete", "categories": {"performance": 99}}

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_analyzer_cache_and_inflight_coalescing() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return httpx.Response(
            200,
            headers={"content-type": "text/html", "content-encoding": "br"},
            content=OPTIMIZED_HTML,
        )

    settings = make_settings(cache_ttl_seconds=60)
    fetcher = make_fetcher(handler, settings=settings)
    analyzer = Analyzer(settings, fetcher=fetcher)
    try:
        reports = await asyncio.gather(
            analyzer.analyze("https://saas.test"),
            analyzer.analyze("https://saas.test/"),
            analyzer.analyze("https://saas.test/#fragment"),
        )
        cached = await analyzer.analyze("https://saas.test")
    finally:
        await analyzer.close()
    assert calls == 1
    assert all(report.score.overall == reports[0].score.overall for report in reports)
    assert cached.final_url == "https://saas.test/"


@pytest.mark.asyncio
async def test_analyzer_optional_pagespeed_and_artifact() -> None:
    fetcher = make_fetcher(
        lambda request: httpx.Response(
            200, headers={"content-type": "text/html"}, content=OPTIMIZED_HTML
        )
    )
    pagespeed = FakePageSpeed()
    analyzer = Analyzer(make_settings(), fetcher=fetcher, pagespeed=pagespeed)  # type: ignore[arg-type]
    artifact = await analyzer.analyze_artifact("https://saas.test", include_pagespeed=True)
    await analyzer.close()
    assert artifact.report.performance["categories"]["performance"] == 99
    assert artifact.parsed.internal_urls
    assert pagespeed.calls == ["https://saas.test/"]
    assert pagespeed.closed is True


@pytest.mark.asyncio
async def test_failed_analysis_does_not_poison_inflight_map() -> None:
    fetcher = make_fetcher(
        lambda request: httpx.Response(
            200, headers={"content-type": "application/json"}, json={"x": 1}
        )
    )
    analyzer = Analyzer(make_settings(), fetcher=fetcher)
    try:
        for _ in range(2):
            with pytest.raises(FetchError) as caught:
                await analyzer.analyze("https://saas.test")
            assert caught.value.code == "unsupported_content_type"
        assert analyzer._inflight == {}
    finally:
        await analyzer.close()


@pytest.mark.asyncio
async def test_cancelled_waiter_does_not_leak_and_completed_work_is_cached() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return httpx.Response(
            200,
            headers={"content-type": "text/html", "content-encoding": "br"},
            content=OPTIMIZED_HTML,
        )

    settings = make_settings(cache_ttl_seconds=60)
    analyzer = Analyzer(settings, fetcher=make_fetcher(handler, settings=settings))
    waiting = asyncio.create_task(analyzer.analyze("https://saas.test"))
    await started.wait()
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    release.set()
    for _ in range(20):
        if not analyzer._inflight:
            break
        await asyncio.sleep(0.005)
    try:
        report = await analyzer.analyze("https://saas.test")
    finally:
        await analyzer.close()
    assert analyzer._inflight == {}
    assert report.score.overall >= 90
    assert calls == 1
