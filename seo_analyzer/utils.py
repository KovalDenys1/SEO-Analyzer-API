import re
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMETERS = {
    "fbclid",
    "gclid",
    "gbraid",
    "mc_cid",
    "mc_eid",
    "msclkid",
    "ref",
    "referrer",
    "source",
    "wbraid",
}


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_url(url: str, *, keep_query: bool = True) -> str:
    """Normalize a crawl key without changing meaningful path semantics."""

    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    hostname = (parts.hostname or "").lower().rstrip(".")
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    default_port = (scheme == "http" and parts.port == 80) or (
        scheme == "https" and parts.port == 443
    )
    netloc = hostname
    if parts.port and not default_port:
        netloc = f"{hostname}:{parts.port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    query = ""
    if keep_query and parts.query:
        params = [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMETERS
        ]
        query = urlencode(sorted(params))
    return urlunsplit((scheme, netloc, path, query, ""))


def origin_for(url: str) -> str:
    parts = urlsplit(url)
    hostname = parts.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    default_port = (parts.scheme == "http" and parts.port == 80) or (
        parts.scheme == "https" and parts.port == 443
    )
    netloc = hostname if not parts.port or default_port else f"{hostname}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, "", "", ""))


def same_site(candidate_url: str, base_url: str, *, include_subdomains: bool = False) -> bool:
    candidate = (urlsplit(candidate_url).hostname or "").lower().rstrip(".")
    base = (urlsplit(base_url).hostname or "").lower().rstrip(".")
    if candidate == base or candidate.removeprefix("www.") == base.removeprefix("www."):
        return True
    if not include_subdomains:
        return False
    # Subdomain scope is deliberately anchored to the exact requested host.
    # Broadly stripping ``www`` here without a public-suffix database could turn
    # www.co.uk or a multi-tenant host into a cross-tenant crawl boundary. The
    # exact root/www pair above is safe because no arbitrary sibling is admitted.
    return candidate.endswith(f".{base}")


def grade_for(score: float) -> tuple[str, str]:
    if score >= 90:
        return "A", "excellent"
    if score >= 80:
        return "B", "strong"
    if score >= 70:
        return "C", "fair"
    if score >= 55:
        return "D", "weak"
    return "F", "critical"


def clamp(value: float, minimum: float = 0, maximum: float = 100) -> float:
    return max(minimum, min(maximum, value))


def compact_text(value: str, limit: int = 240) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    return normalized if len(normalized) <= limit else f"{normalized[: limit - 1]}…"
