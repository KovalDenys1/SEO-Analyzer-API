import httpx
import pytest
from conftest import make_settings

from seo_analyzer.performance import PageSpeedClient, _extract_field_data


@pytest.mark.asyncio
async def test_pagespeed_disabled_does_not_call_network() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    client = PageSpeedClient(
        make_settings(enable_pagespeed=False), transport=httpx.MockTransport(handler)
    )
    try:
        result = await client.analyze("https://x.test")
    finally:
        await client.close()
    assert result["status"] == "disabled"
    assert called is False


@pytest.mark.asyncio
async def test_pagespeed_extracts_categories_metrics_field_and_opportunities() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["url"] == "https://x.test"
        assert request.url.params["strategy"] == "mobile"
        assert request.url.params["key"] == "secret"
        return httpx.Response(
            200,
            json={
                "lighthouseResult": {
                    "fetchTime": "2026-01-01T00:00:00Z",
                    "lighthouseVersion": "13.0.0",
                    "categories": {
                        "performance": {"score": 0.82},
                        "seo": {"score": 1.0},
                    },
                    "audits": {
                        "largest-contentful-paint": {
                            "numericValue": 2900,
                            "numericUnit": "millisecond",
                            "displayValue": "2.9 s",
                            "score": 0.7,
                        },
                        "unused-javascript": {
                            "title": "Reduce unused JavaScript",
                            "displayValue": "120 KiB",
                            "score": 0.4,
                            "details": {
                                "overallSavingsMs": 500.4,
                                "overallSavingsBytes": 123456.7,
                            },
                        },
                    },
                },
                "loadingExperience": {
                    "id": "https://x.test/",
                    "overall_category": "AVERAGE",
                    "metrics": {
                        "LARGEST_CONTENTFUL_PAINT_MS": {
                            "percentile": 2600,
                            "category": "AVERAGE",
                        }
                    },
                },
                "originLoadingExperience": {},
            },
        )

    client = PageSpeedClient(
        make_settings(enable_pagespeed=True, pagespeed_api_key="secret"),
        transport=httpx.MockTransport(handler),
    )
    try:
        result = await client.analyze("https://x.test")
    finally:
        await client.close()
    assert result["status"] == "complete"
    assert result["categories"] == {"performance": 82, "seo": 100}
    assert result["lab_metrics"]["largest-contentful-paint"]["numeric_value"] == 2900
    assert result["field"]["metrics"]["LARGEST_CONTENTFUL_PAINT_MS"]["percentile"] == 2600
    assert result["origin_field"] is None
    assert result["opportunities"][0]["estimated_savings_ms"] == 500


@pytest.mark.asyncio
async def test_pagespeed_failure_is_nonfatal() -> None:
    client = PageSpeedClient(
        make_settings(enable_pagespeed=True, pagespeed_api_key="must-not-leak"),
        transport=httpx.MockTransport(lambda request: httpx.Response(429, text="quota")),
    )
    try:
        result = await client.analyze("https://x.test")
    finally:
        await client.close()
    assert result["status"] == "error"
    assert "429" in result["reason"]
    assert "must-not-leak" not in result["reason"]
    assert _extract_field_data({}) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exception", "reason"),
    [
        (httpx.ReadTimeout("slow"), "timed out"),
        (httpx.ConnectError("offline"), "request failed"),
    ],
)
async def test_pagespeed_network_errors_are_sanitized(
    exception: httpx.RequestError, reason: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        exception.request = request
        raise exception

    client = PageSpeedClient(
        make_settings(enable_pagespeed=True, pagespeed_api_key="must-not-leak"),
        transport=httpx.MockTransport(handler),
    )
    try:
        result = await client.analyze("https://x.test/private-query?token=also-secret")
    finally:
        await client.close()
    assert reason in result["reason"]
    assert "must-not-leak" not in result["reason"]
    assert "also-secret" not in result["reason"]
