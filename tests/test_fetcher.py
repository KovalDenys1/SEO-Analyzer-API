import ipaddress

import httpx
import pytest
from conftest import PUBLIC_IP, make_fetcher, make_settings

from seo_analyzer.fetcher import FetchError, SafeFetcher


@pytest.mark.asyncio
async def test_fetch_success_pins_ip_and_preserves_host() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["host"] = request.headers["host"]
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8", "etag": "abc"},
            content=b"<html><title>OK</title></html>",
        )

    fetcher = make_fetcher(handler)
    try:
        result = await fetcher.fetch("https://Public.Test/path?q=1#ignored")
    finally:
        await fetcher.close()
    assert seen == {"url": f"https://{PUBLIC_IP}/path?q=1", "host": "public.test"}
    assert result.status_code == 200
    assert result.final_url == "https://public.test/path?q=1"
    assert result.text.startswith("<html>")
    assert result.http_version == "HTTP/1.1"
    assert result.resolved_ip == PUBLIC_IP
    assert result.total_ms >= 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("ftp://example.com/file", "unsupported_scheme"),
        ("https://user:pass@example.com", "credentials_not_allowed"),
        ("https://example.com:8443", "port_not_allowed"),
        ("https://127.0.0.1", "private_network_blocked"),
        ("https://[::1]", "private_network_blocked"),
    ],
)
async def test_url_safety_rejections(url: str, code: str) -> None:
    fetcher = make_fetcher(lambda request: httpx.Response(200, text="ok"))
    try:
        with pytest.raises(FetchError) as caught:
            await fetcher.fetch(url, accepted_content_types=None)
    finally:
        await fetcher.close()
    assert caught.value.code == code


@pytest.mark.asyncio
async def test_mixed_public_private_dns_answer_is_blocked() -> None:
    async def resolver(_hostname: str, _port: int) -> list:
        return [ipaddress.ip_address(PUBLIC_IP), ipaddress.ip_address("10.0.0.1")]

    fetcher = make_fetcher(lambda request: httpx.Response(200), resolver=resolver)
    try:
        with pytest.raises(FetchError, match="private") as caught:
            await fetcher.fetch("https://mixed.test", accepted_content_types=None)
    finally:
        await fetcher.close()
    assert caught.value.code == "private_network_blocked"


@pytest.mark.asyncio
async def test_allow_private_hosts_is_explicit_opt_in() -> None:
    fetcher = make_fetcher(
        lambda request: httpx.Response(200, text="ok"),
        settings=make_settings(allow_private_hosts=True),
        resolver=lambda hostname, port: _addresses("127.0.0.1"),
    )
    try:
        result = await fetcher.fetch("http://localhost", accepted_content_types=None)
    finally:
        await fetcher.close()
    assert result.status_code == 200


async def _addresses(value: str) -> list:
    return [ipaddress.ip_address(value)]


@pytest.mark.asyncio
async def test_redirect_is_revalidated_and_private_target_blocked() -> None:
    async def resolver(hostname: str, _port: int) -> list:
        value = "10.0.0.9" if hostname == "internal.test" else PUBLIC_IP
        return [ipaddress.ip_address(value)]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://internal.test/metadata"})

    fetcher = make_fetcher(handler, resolver=resolver)
    try:
        with pytest.raises(FetchError) as caught:
            await fetcher.fetch("https://public.test")
    finally:
        await fetcher.close()
    assert caught.value.code == "private_network_blocked"


@pytest.mark.asyncio
async def test_redirect_chain_success_and_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/":
            return httpx.Response(301, headers={"location": "/next"})
        if path == "/next":
            return httpx.Response(302, headers={"location": "https://other.test/final"})
        return httpx.Response(200, headers={"content-type": "text/html"}, text="done")

    fetcher = make_fetcher(handler)
    try:
        result = await fetcher.fetch("https://public.test")
    finally:
        await fetcher.close()
    assert result.final_url == "https://other.test/final"
    assert [hop.status_code for hop in result.redirects] == [301, 302]

    looping = make_fetcher(
        lambda request: httpx.Response(302, headers={"location": "/again"}),
        settings=make_settings(max_redirects=1),
    )
    try:
        with pytest.raises(FetchError) as caught:
            await looping.fetch("https://public.test")
    finally:
        await looping.close()
    assert caught.value.code == "too_many_redirects"


@pytest.mark.asyncio
async def test_response_size_and_content_type_limits() -> None:
    large = make_fetcher(
        lambda request: httpx.Response(
            200, headers={"content-type": "text/html"}, content=b"x" * 20
        )
    )
    try:
        with pytest.raises(FetchError) as caught:
            await large.fetch("https://public.test", max_bytes=10)
    finally:
        await large.close()
    assert caught.value.code == "response_too_large"
    assert caught.value.status_code == 413

    json_fetcher = make_fetcher(
        lambda request: httpx.Response(
            200, headers={"content-type": "application/json"}, json={"ok": True}
        )
    )
    try:
        with pytest.raises(FetchError) as caught:
            await json_fetcher.fetch("https://public.test")
        accepted = await json_fetcher.fetch("https://public.test", accepted_content_types=None)
    finally:
        await json_fetcher.close()
    assert caught.value.code == "unsupported_content_type"
    assert accepted.content_type == "application/json"


@pytest.mark.asyncio
async def test_network_failure_and_empty_dns_are_normalized() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    fetcher = make_fetcher(broken)
    try:
        with pytest.raises(FetchError) as caught:
            await fetcher.fetch("https://public.test")
    finally:
        await fetcher.close()
    assert caught.value.code == "upstream_unreachable"
    assert caught.value.status_code == 502

    async def empty_resolver(_hostname: str, _port: int) -> list:
        return []

    no_dns = make_fetcher(lambda request: httpx.Response(200), resolver=empty_resolver)
    try:
        with pytest.raises(FetchError) as caught:
            await no_dns.validate("https://missing.test")
    finally:
        await no_dns.close()
    assert caught.value.code == "dns_resolution_failed"


@pytest.mark.asyncio
async def test_static_resolver_handles_literal_ip() -> None:
    assert await SafeFetcher._resolve(PUBLIC_IP, 443) == [ipaddress.ip_address(PUBLIC_IP)]
