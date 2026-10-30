import re

from seo_analyzer.fetcher import FetchError, FetchResult

CHALLENGE_STATUSES = {403, 405, 429, 503}
CHALLENGE_TITLE = re.compile(
    r"just a moment|attention required|security check|checking your browser|verify you are human"
    r"|are you a robot|access denied|access to this page has been denied|pardon our interruption|ddos-guard|request blocked",
    re.IGNORECASE,
)
CHALLENGE_MARKUP = (
    b"/cdn-cgi/challenge-platform/h/",
    b"challenges.cloudflare.com",
    b"captcha-delivery.com",
    b"_Incapsula_Resource",
    b"/_sec/cp_challenge/",
    b"px-captcha",
)
TITLE = re.compile(rb"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def bot_protection_vendor(result: FetchResult) -> str | None:
    """Name the service that answered with a challenge instead of the page, or None."""
    headers = {key.lower(): value.lower() for key, value in result.headers.items()}
    if headers.get("cf-mitigated") == "challenge":
        return "Cloudflare"
    if headers.get("x-amzn-waf-action") in {"captcha", "challenge"}:
        return "AWS WAF"
    if result.status_code not in CHALLENGE_STATUSES:
        return None
    head = result.content[:20_000]
    title_match = TITLE.search(head)
    title = title_match.group(1).decode("utf-8", "replace") if title_match else ""
    if any(marker in head for marker in CHALLENGE_MARKUP) or CHALLENGE_TITLE.search(title):
        server = headers.get("server", "")
        if b"captcha-delivery.com" in head:
            return "DataDome"
        if b"px-captcha" in head:
            return "PerimeterX"
        if "cloudflare" in server:
            return "Cloudflare"
        if "akamai" in server:
            return "Akamai"
        return "bot protection"
    return None


def raise_if_bot_protected(result: FetchResult) -> None:
    vendor = bot_protection_vendor(result)
    if vendor is None:
        return
    raise FetchError(
        "blocked_by_bot_protection",
        f"The site answered with a {vendor} challenge (HTTP {result.status_code}) instead of the page, "
        "so there was nothing real to audit",
        status_code=502,
    )
