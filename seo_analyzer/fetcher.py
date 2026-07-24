import asyncio
import ipaddress
import socket
import time
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass
from typing import ClassVar, TypeAlias
from urllib.parse import urljoin

import httpx

from seo_analyzer.config import Settings
from seo_analyzer.utils import normalize_url

IPAddress: TypeAlias = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver: TypeAlias = Callable[[str, int], Awaitable[list[IPAddress]]]


class FetchError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(slots=True)
class RedirectHop:
    url: str
    status_code: int
    location: str


@dataclass(slots=True)
class FetchResult:
    requested_url: str
    final_url: str
    status_code: int
    headers: dict[str, str]
    content: bytes
    encoding: str
    content_type: str
    http_version: str
    resolved_ip: str
    redirects: list[RedirectHop]
    ttfb_ms: int
    download_ms: int
    total_ms: int

    @property
    def text(self) -> str:
        try:
            return self.content.decode(self.encoding, errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")


class SafeFetcher:
    """Async HTTP client that pins validated public DNS answers to prevent SSRF."""

    REDIRECT_CODES: ClassVar[set[int]] = {301, 302, 303, 307, 308}

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: Resolver | None = None,
    ) -> None:
        self.settings = settings
        self._resolver = resolver or self._resolve
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_fetches)
        timeout = httpx.Timeout(settings.fetch_timeout_seconds)
        limits = httpx.Limits(
            max_connections=settings.max_concurrent_fetches,
            max_keepalive_connections=settings.max_concurrent_fetches,
        )
        self._client = httpx.AsyncClient(
            timeout=timeout,
            limits=limits,
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def validate(self, url: str) -> tuple[httpx.URL, list[IPAddress]]:
        raw_url = url.strip()
        try:
            parsed = httpx.URL(raw_url)
        except httpx.InvalidURL as exc:
            raise FetchError("invalid_url", "The supplied URL is invalid") from exc
        if parsed.scheme not in {"http", "https"}:
            raise FetchError("unsupported_scheme", "Only http and https URLs are supported")
        if not parsed.host:
            raise FetchError("missing_host", "The URL must include a hostname")
        if parsed.username or parsed.password:
            raise FetchError("credentials_not_allowed", "Credentials in URLs are not allowed")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if port not in self.settings.parsed_allowed_ports:
            raise FetchError("port_not_allowed", f"Port {port} is not allowed")
        try:
            literal_address = ipaddress.ip_address(parsed.host)
        except ValueError:
            literal_address = None
        addresses = (
            [literal_address]
            if literal_address is not None
            else await self._resolver(parsed.host, port)
        )
        if not addresses:
            raise FetchError(
                "dns_resolution_failed", "The hostname did not resolve", status_code=502
            )
        blocked = [address for address in addresses if not address.is_global]
        if blocked and not self.settings.allow_private_hosts:
            raise FetchError(
                "private_network_blocked",
                "The hostname resolves to a private, loopback, link-local, or reserved address",
            )
        return parsed, addresses

    async def fetch(
        self,
        url: str,
        *,
        accepted_content_types: Collection[str] | None = ("text/html", "application/xhtml+xml"),
        max_bytes: int | None = None,
    ) -> FetchResult:
        limit = min(max_bytes or self.settings.max_response_bytes, self.settings.max_response_bytes)
        parsed_input, _ = await self.validate(url)
        requested = normalize_url(str(parsed_input), keep_query=True)
        current = requested
        redirects: list[RedirectHop] = []
        started_at = time.perf_counter()

        async with self._semaphore:
            for redirect_count in range(self.settings.max_redirects + 1):
                parsed, addresses = await self.validate(current)
                address = sorted(addresses, key=lambda item: (item.version != 4, str(item)))[0]
                result = await self._request_once(parsed, address, limit)
                if (
                    result.status_code not in self.REDIRECT_CODES
                    or "location" not in result.headers
                ):
                    result.requested_url = requested
                    result.final_url = current
                    result.redirects = redirects
                    result.total_ms = round((time.perf_counter() - started_at) * 1_000)
                    self._check_content_type(result, accepted_content_types)
                    return result
                if redirect_count >= self.settings.max_redirects:
                    raise FetchError(
                        "too_many_redirects", "The redirect limit was exceeded", status_code=502
                    )
                location = result.headers["location"]
                next_url = normalize_url(urljoin(current, location), keep_query=True)
                redirects.append(
                    RedirectHop(url=current, status_code=result.status_code, location=next_url)
                )
                current = next_url

        raise FetchError("fetch_failed", "The page could not be fetched", status_code=502)

    async def _request_once(
        self, public_url: httpx.URL, address: IPAddress, max_bytes: int
    ) -> FetchResult:
        connect_url = public_url.copy_with(host=str(address))
        host_header = public_url.host
        if ":" in host_header and not host_header.startswith("["):
            host_header = f"[{host_header}]"
        default_port = (public_url.scheme == "http" and public_url.port == 80) or (
            public_url.scheme == "https" and public_url.port == 443
        )
        if public_url.port and not default_port:
            host_header = f"{host_header}:{public_url.port}"
        request = self._client.build_request(
            "GET",
            connect_url,
            headers={
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8",
                "host": host_header,
                "user-agent": self.settings.user_agent,
            },
            extensions={"sni_hostname": public_url.host},
        )
        started_at = time.perf_counter()
        try:
            response = await self._client.send(request, stream=True)
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
            raise FetchError(
                "upstream_unreachable", f"Upstream request failed: {exc}", status_code=502
            ) from exc
        headers_at = time.perf_counter()
        try:
            declared_length = response.headers.get("content-length")
            if declared_length and declared_length.isdigit() and int(declared_length) > max_bytes:
                raise FetchError(
                    "response_too_large",
                    f"Response exceeds the {max_bytes}-byte limit",
                    status_code=413,
                )
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise FetchError(
                        "response_too_large",
                        f"Decompressed response exceeds the {max_bytes}-byte limit",
                        status_code=413,
                    )
        finally:
            await response.aclose()
        finished_at = time.perf_counter()
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        encoding = response.encoding or "utf-8"
        return FetchResult(
            requested_url=str(public_url),
            final_url=str(public_url),
            status_code=response.status_code,
            headers={key.lower(): value for key, value in response.headers.items()},
            content=bytes(body),
            encoding=encoding,
            content_type=content_type,
            http_version=response.http_version,
            resolved_ip=str(address),
            redirects=[],
            ttfb_ms=round((headers_at - started_at) * 1_000),
            download_ms=round((finished_at - headers_at) * 1_000),
            total_ms=round((finished_at - started_at) * 1_000),
        )

    @staticmethod
    def _check_content_type(
        result: FetchResult, accepted_content_types: Collection[str] | None
    ) -> None:
        if accepted_content_types is None:
            return
        if result.content_type not in accepted_content_types:
            value = result.content_type or "missing"
            raise FetchError(
                "unsupported_content_type",
                f"Expected {', '.join(accepted_content_types)} but received {value}",
                status_code=415,
            )

    @staticmethod
    async def _resolve(hostname: str, port: int) -> list[IPAddress]:
        try:
            direct = ipaddress.ip_address(hostname)
        except ValueError:
            direct = None
        if direct is not None:
            return [direct]
        loop = asyncio.get_running_loop()
        try:
            records = await loop.getaddrinfo(
                hostname,
                port,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
        except socket.gaierror as exc:
            raise FetchError(
                "dns_resolution_failed", f"DNS resolution failed for {hostname}", status_code=502
            ) from exc
        addresses = {ipaddress.ip_address(record[4][0]) for record in records}
        return sorted(addresses, key=lambda item: (item.version, str(item)))
