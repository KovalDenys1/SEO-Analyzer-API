import asyncio

import pytest
from pydantic import ValidationError

from seo_analyzer.cache import AsyncTTLCache
from seo_analyzer.config import Settings
from seo_analyzer.utils import (
    clamp,
    compact_text,
    grade_for,
    normalize_url,
    origin_for,
    same_site,
    utc_now_iso,
)


def test_url_helpers_normalize_tracking_and_origin() -> None:
    url = normalize_url("HTTPS://WWW.Example.COM:443//products///one?utm_source=x&b=2&a=1#fragment")
    assert url == "https://www.example.com/products/one?a=1&b=2"
    assert origin_for(url) == "https://www.example.com"
    assert normalize_url("http://example.com:8080/path", keep_query=False) == (
        "http://example.com:8080/path"
    )


@pytest.mark.parametrize(
    ("candidate", "base", "subdomains", "expected"),
    [
        ("https://example.com/a", "https://example.com", False, True),
        ("https://docs.example.com/a", "https://example.com", False, False),
        ("https://docs.example.com/a", "https://example.com", True, True),
        ("https://example.com/a", "https://www.example.com", False, True),
        ("https://docs.example.com/a", "https://www.example.com", True, False),
        ("https://tenant.co.uk/a", "https://www.co.uk", True, False),
        ("https://notexample.com/a", "https://example.com", True, False),
    ],
)
def test_same_site(candidate: str, base: str, subdomains: bool, expected: bool) -> None:
    assert same_site(candidate, base, include_subdomains=subdomains) is expected


@pytest.mark.parametrize(
    ("score", "grade", "rating"),
    [
        (95, "A", "excellent"),
        (85, "B", "strong"),
        (75, "C", "fair"),
        (60, "D", "weak"),
        (20, "F", "critical"),
    ],
)
def test_grades(score: float, grade: str, rating: str) -> None:
    assert grade_for(score) == (grade, rating)


def test_misc_helpers() -> None:
    assert clamp(-2) == 0
    assert clamp(101) == 100
    assert compact_text(" a\n  b ", 20) == "a b"
    assert compact_text("abcdefgh", 5) == "abcd…"
    assert utc_now_iso().endswith("Z")


def test_settings_parse_lists_and_validate() -> None:
    settings = Settings(allowed_ports="80, 443,8080", cors_origins="https://a.test, https://b.test")
    assert settings.parsed_allowed_ports == {80, 443, 8080}
    assert settings.parsed_cors_origins == ["https://a.test", "https://b.test"]
    with pytest.raises(ValidationError):
        Settings(max_redirects=99)
    for invalid in ("", "443,not-a-port", "0", "65536"):
        with pytest.raises(ValidationError):
            Settings(allowed_ports=invalid)
    with pytest.raises(ValidationError):
        Settings(user_agent="unsafe\r\nheader")
    with pytest.raises(ValidationError):
        Settings(robots_user_agent="invalid bot/1.0")
    with pytest.raises(ValidationError):
        Settings(log_level="verbose")


@pytest.mark.asyncio
async def test_ttl_cache_get_evict_expire_and_clear() -> None:
    cache: AsyncTTLCache[str, dict[str, int]] = AsyncTTLCache(maxsize=2, ttl_seconds=0.02)
    await cache.set("a", {"value": 1})
    first = await cache.get("a")
    assert first == {"value": 1}
    assert first is not None
    first["value"] = 99
    assert await cache.get("a") == {"value": 1}
    await cache.set("b", {"value": 2})
    await cache.set("c", {"value": 3})
    assert await cache.get("a") is None
    assert await cache.size() == 2
    await asyncio.sleep(0.03)
    assert await cache.get("b") is None
    await cache.clear()
    assert await cache.size() == 0


@pytest.mark.asyncio
async def test_disabled_cache_never_stores() -> None:
    cache: AsyncTTLCache[str, int] = AsyncTTLCache(maxsize=1, ttl_seconds=0)
    await cache.set("a", 1)
    assert await cache.get("a") is None
