import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from seo_analyzer.fetcher import FetchResult
from seo_analyzer.models import PageType
from seo_analyzer.saas import extract_saas_signals
from seo_analyzer.utils import compact_text, normalize_url, same_site

STOP_WORDS = {
    # English
    "about",
    "after",
    "also",
    "and",
    "are",
    "been",
    "before",
    "but",
    "can",
    "for",
    "from",
    "have",
    "how",
    "into",
    "more",
    "not",
    "our",
    "that",
    "the",
    "their",
    "this",
    "to",
    "was",
    "we",
    "what",
    "when",
    "where",
    "which",
    "with",
    "you",
    "your",
    # Russian / Ukrainian
    "без",
    "был",
    "была",
    "быть",
    "для",
    "его",
    "или",
    "как",
    "мы",
    "на",
    "наш",
    "не",
    "но",
    "они",
    "от",
    "по",
    "при",
    "с",
    "так",
    "это",
    "ви",
    "з",
    "та",
    "це",
    "що",
}

GENERIC_ANCHORS = {
    "click here",
    "here",
    "learn more",
    "more",
    "read more",
    "details",
    "узнать больше",
    "подробнее",
    "здесь",
    "дізнатися більше",
    "детальніше",
    "тут",
}

MAX_EXTRACTED_LINKS = 5_000
MAX_JSONLD_NODES = 20_000


@dataclass(slots=True)
class ParsedPage:
    sections: dict[str, Any]
    internal_urls: list[str]
    external_urls: list[str]
    page_type: PageType
    title: str
    description: str
    h1_texts: list[str]
    text_signature: str


def _meta_values(soup: BeautifulSoup, key: str, value: str) -> list[str]:
    values: list[str] = []
    for tag in soup.find_all("meta"):
        if str(tag.get(key, "")).strip().lower() == value.lower():
            content = compact_text(str(tag.get("content", "")), 2_000)
            if content:
                values.append(content)
    return values


def _link_rel(tag: Tag) -> set[str]:
    rel = tag.attrs.get("rel")
    if rel is None:
        return set()
    values = rel.split() if isinstance(rel, str) else rel
    return {str(value).lower() for value in values}


def _absolute_url(base_url: str, raw_url: str) -> str | None:
    raw_url = raw_url.strip()
    if not raw_url or raw_url.startswith("#"):
        return None
    try:
        parsed = urlsplit(raw_url)
        if parsed.scheme and parsed.scheme.lower() not in {"http", "https"}:
            return None
        absolute = urljoin(base_url, raw_url)
        absolute_parts = urlsplit(absolute)
        if absolute_parts.scheme.lower() not in {"http", "https"} or not absolute_parts.hostname:
            return None
        return normalize_url(absolute, keep_query=True)
    except (ValueError, UnicodeError):
        return None


def _extract_structured_data(soup: BeautifulSoup) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    types: set[str] = set()

    for index, script in enumerate(soup.find_all("script")):
        script_type = str(script.get("type", "")).split(";", 1)[0].strip().lower()
        if script_type != "application/ld+json":
            continue
        raw = script.string or script.get_text()
        raw = re.sub(r"^\s*<!--|-->\s*$", "", raw.strip())
        if not raw:
            errors.append({"block": index, "error": "empty JSON-LD block"})
            continue
        try:
            data = json.loads(raw)
            block_types = _types_for_value(data)
        except (json.JSONDecodeError, TypeError, RecursionError, ValueError) as exc:
            errors.append({"block": index, "error": compact_text(str(exc), 200)})
            continue
        types.update(block_types)
        blocks.append(
            {
                "block": index,
                "root_type": type(data).__name__,
                "types": sorted(block_types),
            }
        )
    return {
        "valid_blocks": len(blocks),
        "invalid_blocks": len(errors),
        "types": sorted(types),
        "blocks": blocks[:30],
        "errors": errors[:30],
        "format_note": "JSON-LD is parsed syntactically; eligibility and property completeness require a schema-specific validator.",
    }


def _types_for_value(value: Any) -> set[str]:
    found: set[str] = set()
    pending = [value]
    visited = 0
    while pending:
        current = pending.pop()
        visited += 1
        if visited > MAX_JSONLD_NODES:
            raise ValueError(f"JSON-LD exceeds the {MAX_JSONLD_NODES}-node analysis limit")
        if isinstance(current, dict):
            item_type = current.get("@type")
            if isinstance(item_type, str):
                found.add(item_type)
            elif isinstance(item_type, list):
                found.update(str(entry) for entry in item_type)
            pending.extend(current.values())
        elif isinstance(current, list):
            pending.extend(current)
    return found


def _extract_content(soup: BeautifulSoup) -> tuple[dict[str, Any], str, str]:
    content_soup = BeautifulSoup(str(soup), "html.parser")
    for tag in content_soup.find_all(
        ["script", "style", "noscript", "svg", "template", "canvas", "iframe"]
    ):
        tag.decompose()
    full_text = compact_text(content_soup.get_text(" ", strip=True), 500_000)
    primary = content_soup.find("main") or content_soup.find("article") or content_soup.body
    if primary is None:
        primary_text = full_text
    else:
        for tag in primary.find_all(["nav", "footer", "header", "aside"]):
            tag.decompose()
        primary_text = compact_text(primary.get_text(" ", strip=True), 500_000)

    words = re.findall(r"\b[^\W_][\w'’-]*\b", primary_text.lower(), flags=re.UNICODE)
    meaningful = [word for word in words if len(word) > 2 and word not in STOP_WORDS]
    counter = Counter(meaningful)
    top_terms = [
        {
            "term": term,
            "count": count,
            "density_percent": round((count / len(words)) * 100, 2) if words else 0,
        }
        for term, count in counter.most_common(25)
    ]
    sentences = [part for part in re.split(r"[.!?]+", primary_text) if part.strip()]
    paragraph_count = sum(bool(tag.get_text(" ", strip=True)) for tag in content_soup.find_all("p"))
    normalized_signature_text = re.sub(r"\W+", " ", primary_text.lower()).strip()
    signature = hashlib.sha256(normalized_signature_text.encode("utf-8")).hexdigest()
    return (
        {
            "word_count": len(words),
            "meaningful_word_count": len(meaningful),
            "unique_meaningful_words": len(counter),
            "sentence_count": len(sentences),
            "paragraph_count": paragraph_count,
            "average_sentence_words": round(len(words) / len(sentences), 1) if sentences else 0,
            "top_terms": top_terms,
            "text_to_html_ratio_percent": 0,  # populated by parse_page once byte size is known
            "author": _first_meta(soup, "name", "author"),
            "published_time": _first_meta(soup, "property", "article:published_time"),
            "modified_time": _first_meta(soup, "property", "article:modified_time"),
            "sample": compact_text(primary_text, 500),
        },
        full_text,
        signature,
    )


def _first_meta(soup: BeautifulSoup, key: str, value: str) -> str | None:
    values = _meta_values(soup, key, value)
    return values[0] if values else None


def _extract_links(
    soup: BeautifulSoup,
    base_url: str,
    *,
    include_subdomains: bool,
) -> tuple[dict[str, Any], list[str], list[str]]:
    records: list[dict[str, Any]] = []
    skipped_non_web = 0
    empty_anchor_count = 0
    generic_anchor_count = 0
    links_truncated = False
    for index, anchor in enumerate(soup.find_all("a")):
        if index >= MAX_EXTRACTED_LINKS:
            links_truncated = True
            break
        href = anchor.get("href")
        if not href:
            continue
        absolute = _absolute_url(base_url, str(href))
        if absolute is None:
            skipped_non_web += 1
            continue
        text = compact_text(anchor.get_text(" ", strip=True), 200)
        image_alt = " ".join(
            compact_text(str(image.get("alt", "")), 100) for image in anchor.find_all("img")
        ).strip()
        effective_anchor = text or image_alt or compact_text(str(anchor.get("title", "")), 200)
        if not effective_anchor:
            empty_anchor_count += 1
        if effective_anchor.lower() in GENERIC_ANCHORS:
            generic_anchor_count += 1
        rel = sorted(_link_rel(anchor))
        records.append(
            {
                "url": absolute,
                "anchor": effective_anchor,
                "rel": rel,
                "internal": same_site(absolute, base_url, include_subdomains=include_subdomains),
            }
        )

    unique: dict[str, dict[str, Any]] = {}
    for record in records:
        existing = unique.get(record["url"])
        if existing is None or (not existing["anchor"] and record["anchor"]):
            unique[record["url"]] = record
    internal = [record for record in unique.values() if record["internal"]]
    external = [record for record in unique.values() if not record["internal"]]
    nofollow = sum("nofollow" in record["rel"] for record in records)
    sponsored = sum("sponsored" in record["rel"] for record in records)
    ugc = sum("ugc" in record["rel"] for record in records)
    return (
        {
            "total": len(records),
            "unique": len(unique),
            "internal": {"count": len(internal), "items": internal[:100]},
            "external": {"count": len(external), "items": external[:100]},
            "nofollow": nofollow,
            "sponsored": sponsored,
            "ugc": ugc,
            "empty_anchor": empty_anchor_count,
            "generic_anchor": generic_anchor_count,
            "non_web_or_fragment_skipped": skipped_non_web,
            "truncated": links_truncated,
            "analysis_limit": MAX_EXTRACTED_LINKS,
            "broken": [],
            "broken_note": "Broken-link status is populated by a site crawl; a single-page parse does not request every target.",
        },
        [record["url"] for record in internal],
        [record["url"] for record in external],
    )


def _extract_images(soup: BeautifulSoup, base_url: str) -> dict[str, Any]:
    images: list[dict[str, Any]] = []
    for image in soup.find_all("img"):
        raw_src = image.get("src") or image.get("data-src") or ""
        src = _absolute_url(base_url, str(raw_src)) if raw_src else None
        has_alt_attribute = image.has_attr("alt")
        alt = compact_text(str(image.get("alt", "")), 300)
        decorative = (
            (has_alt_attribute and alt == "")
            or str(image.get("role", "")).lower() == "presentation"
            or str(image.get("aria-hidden", "")).lower() == "true"
        )
        parent_link = image.find_parent("a")
        linked = parent_link is not None
        link_has_usable_text = False
        if parent_link is not None:
            link_text = compact_text(parent_link.get_text(" ", strip=True), 300)
            link_title = compact_text(str(parent_link.get("title", "")), 300)
            linked_image_alts = [
                compact_text(str(linked_image.get("alt", "")), 300)
                for linked_image in parent_link.find_all("img")
            ]
            link_has_usable_text = bool(link_text or link_title or any(linked_image_alts))
        images.append(
            {
                "src": src,
                "alt": alt,
                "has_alt_attribute": has_alt_attribute,
                "decorative": decorative,
                "linked": linked,
                "link_has_usable_text": link_has_usable_text,
                "has_dimensions": bool(image.get("width") and image.get("height")),
                "loading": image.get("loading"),
            }
        )
    missing_alt = [image for image in images if not image["has_alt_attribute"]]
    empty_alt = [image for image in images if image["has_alt_attribute"] and not image["alt"]]
    linked_without_text = [
        image for image in images if image["linked"] and not image["link_has_usable_text"]
    ]
    missing_dimensions = [image for image in images if not image["has_dimensions"]]
    return {
        "total": len(images),
        "with_descriptive_alt": sum(bool(image["alt"]) for image in images),
        "missing_alt_attribute": len(missing_alt),
        "empty_alt_decorative_candidates": len(empty_alt),
        "linked_without_alt": len(linked_without_text),
        "missing_dimensions": len(missing_dimensions),
        "lazy_loaded": sum(image["loading"] == "lazy" for image in images),
        "issue_samples": {
            "missing_alt": [image["src"] for image in missing_alt[:20]],
            "linked_without_alt": [image["src"] for image in linked_without_text[:20]],
            "missing_dimensions": [image["src"] for image in missing_dimensions[:20]],
        },
        "alt_note": 'alt="" can be correct for decorative images; only a missing attribute and linked images without usable text are flagged.',
    }


def _extract_headings(soup: BeautifulSoup) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    counts = {f"h{level}": 0 for level in range(1, 7)}
    skipped_levels: list[dict[str, int]] = []
    previous_level = 0
    for heading in soup.find_all(re.compile(r"^h[1-6]$")):
        level = int(heading.name[1])
        text = compact_text(heading.get_text(" ", strip=True), 500)
        counts[f"h{level}"] += 1
        items.append({"level": level, "text": text})
        if previous_level and level > previous_level + 1:
            skipped_levels.append({"from": previous_level, "to": level})
        previous_level = level
    return {
        "counts": counts,
        "items": items[:200],
        "empty": sum(not item["text"] for item in items),
        "skipped_levels": skipped_levels,
    }


def _extract_social(soup: BeautifulSoup) -> dict[str, Any]:
    open_graph: dict[str, str] = {}
    twitter: dict[str, str] = {}
    for tag in soup.find_all("meta"):
        property_name = str(tag.get("property", "")).lower()
        name = str(tag.get("name", "")).lower()
        content = compact_text(str(tag.get("content", "")), 2_000)
        if property_name.startswith("og:") and content:
            open_graph[property_name] = content
        if name.startswith("twitter:") and content:
            twitter[name] = content
    return {
        "open_graph": open_graph,
        "twitter_card": twitter,
        "open_graph_complete": all(
            key in open_graph for key in ("og:title", "og:description", "og:image", "og:url")
        ),
        "twitter_complete": "twitter:card" in twitter
        and ("twitter:image" in twitter or "og:image" in open_graph),
        "ranking_note": "Social preview metadata improves sharing presentation; it is scored separately from core SEO health.",
    }


def _extract_canonical(soup: BeautifulSoup, final_url: str, link_header: str) -> list[str]:
    canonicals: list[str] = []
    for link in soup.find_all("link", href=True):
        if "canonical" in _link_rel(link):
            absolute = _absolute_url(final_url, str(link.get("href", "")))
            if absolute:
                canonicals.append(absolute)
    for match in re.finditer(r"<([^>]+)>\s*;[^,]*\brel\s*=\s*[\"']?canonical", link_header, re.I):
        absolute = _absolute_url(final_url, match.group(1))
        if absolute:
            canonicals.append(absolute)
    return list(dict.fromkeys(canonicals))


def parse_page(fetch: FetchResult, *, include_subdomains: bool = False) -> ParsedPage:
    soup = BeautifulSoup(fetch.content, "html.parser")
    title = compact_text(soup.title.get_text(" ", strip=True), 2_000) if soup.title else ""
    descriptions = _meta_values(soup, "name", "description")
    description = descriptions[0] if descriptions else ""
    keywords = _meta_values(soup, "name", "keywords")
    headings = _extract_headings(soup)
    h1_texts = [item["text"] for item in headings["items"] if item["level"] == 1]
    structured_data = _extract_structured_data(soup)
    links, internal_urls, external_urls = _extract_links(
        soup, fetch.final_url, include_subdomains=include_subdomains
    )
    content, visible_text, text_signature = _extract_content(soup)
    content["text_to_html_ratio_percent"] = (
        round((len(visible_text.encode("utf-8")) / len(fetch.content)) * 100, 1)
        if fetch.content
        else 0
    )
    images = _extract_images(soup, fetch.final_url)
    social = _extract_social(soup)

    robots_meta = _meta_values(soup, "name", "robots")
    googlebot_meta = _meta_values(soup, "name", "googlebot")
    x_robots = fetch.headers.get("x-robots-tag", "")
    robot_text = " ".join([*robots_meta, *googlebot_meta, x_robots]).lower()
    canonical_urls = _extract_canonical(soup, fetch.final_url, fetch.headers.get("link", ""))
    noindex = bool(re.search(r"(?:^|[,\s])noindex(?:$|[,\s])", robot_text))
    indexable_status = 200 <= fetch.status_code < 300
    indexable = indexable_status and not noindex

    html_tag = soup.find("html")
    html_lang = compact_text(str(html_tag.get("lang", "")), 50) if html_tag else ""
    hreflang: list[dict[str, str]] = []
    for link in soup.find_all("link", href=True):
        if "alternate" in _link_rel(link) and link.get("hreflang"):
            absolute = _absolute_url(fetch.final_url, str(link.get("href", "")))
            if absolute:
                hreflang.append({"lang": str(link.get("hreflang", "")).lower(), "url": absolute})

    viewport_values = _meta_values(soup, "name", "viewport")
    viewport = viewport_values[0] if viewport_values else ""
    charset = ""
    charset_meta = soup.find("meta", charset=True)
    if charset_meta:
        charset = str(charset_meta.get("charset", ""))
    elif "charset=" in fetch.headers.get("content-type", "").lower():
        charset = fetch.encoding

    metadata = {
        "title": title,
        "title_characters": len(title),
        "title_words": len(title.split()),
        "description": description,
        "description_characters": len(description),
        "description_count": len(descriptions),
        "keywords": keywords[0] if keywords else "",
        "keywords_note": "meta keywords are extracted for compatibility but are not scored.",
        "canonical": canonical_urls[0] if len(canonical_urls) == 1 else None,
        "canonical_urls": canonical_urls,
        "favicon": next(
            (
                _absolute_url(fetch.final_url, str(link.get("href", "")))
                for link in soup.find_all("link", href=True)
                if _link_rel(link) & {"icon", "shortcut icon"}
            ),
            None,
        ),
        "generator": _first_meta(soup, "name", "generator"),
        "length_note": "Character counts are preview heuristics, not hard Google limits.",
    }
    page_type_info = extract_saas_signals(
        soup,
        url=fetch.final_url,
        title=title,
        h1_texts=h1_texts,
        visible_text=visible_text,
        internal_urls=internal_urls,
        schema_types=structured_data["types"],
    )
    page_type = PageType(page_type_info["page_type"]["type"])
    sections = {
        "page_type": page_type_info["page_type"],
        "fetch": {
            "status_code": fetch.status_code,
            "http_version": fetch.http_version,
            "content_type": fetch.content_type,
            "content_bytes": len(fetch.content),
            "resolved_ip": fetch.resolved_ip,
            "redirects": [
                {"url": hop.url, "status_code": hop.status_code, "location": hop.location}
                for hop in fetch.redirects
            ],
            "timing": {
                "ttfb_ms": fetch.ttfb_ms,
                "download_ms": fetch.download_ms,
                "total_ms": fetch.total_ms,
            },
            "delivery": {
                "content_encoding": fetch.headers.get("content-encoding"),
                "cache_control": fetch.headers.get("cache-control"),
                "etag": bool(fetch.headers.get("etag")),
            },
        },
        "indexability": {
            "indexable": indexable,
            "status_allows_indexing": indexable_status,
            "noindex": noindex,
            "robots_meta": robots_meta,
            "googlebot_meta": googlebot_meta,
            "x_robots_tag": x_robots or None,
            "canonical": canonical_urls[0] if len(canonical_urls) == 1 else None,
            "canonical_count": len(canonical_urls),
            "canonical_is_self": len(canonical_urls) == 1
            and normalize_url(canonical_urls[0]) == normalize_url(fetch.final_url),
        },
        "metadata": metadata,
        "headings": headings,
        "content": content,
        "links": links,
        "images": images,
        "social": social,
        "structured_data": structured_data,
        "international": {
            "html_lang": html_lang or None,
            "hreflang": hreflang[:200],
            "hreflang_count": len(hreflang),
            "has_x_default": any(item["lang"] == "x-default" for item in hreflang),
        },
        "mobile": {
            "viewport": viewport or None,
            "responsive_viewport": "width=device-width" in viewport.lower().replace(" ", ""),
            "charset": charset or None,
        },
        "performance": {
            "status": "network_only",
            "network_timing": {
                "ttfb_ms": fetch.ttfb_ms,
                "download_ms": fetch.download_ms,
                "total_ms": fetch.total_ms,
            },
            "core_web_vitals": None,
            "note": "A server-side HTML request cannot measure LCP, INP, or CLS. Enable PageSpeed integration for browser lab/field data.",
        },
        "saas": {key: value for key, value in page_type_info.items() if key != "page_type"},
    }
    return ParsedPage(
        sections=sections,
        internal_urls=list(dict.fromkeys(internal_urls)),
        external_urls=list(dict.fromkeys(external_urls)),
        page_type=page_type,
        title=title,
        description=description,
        h1_texts=h1_texts,
        text_signature=text_signature,
    )
