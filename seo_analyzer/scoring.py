from collections import defaultdict
from typing import Any
from urllib.parse import urlsplit

from seo_analyzer.models import (
    Effort,
    Impact,
    Issue,
    PageType,
    Recommendation,
    ScoreBreakdown,
    Severity,
)
from seo_analyzer.parser import ParsedPage
from seo_analyzer.utils import clamp, grade_for, normalize_url

SEO_CATEGORY_WEIGHTS = {
    "indexability": 0.20,
    "on_page": 0.20,
    "content": 0.20,
    "links": 0.15,
    "technical": 0.10,
    "structured_data": 0.05,
    "media_social": 0.05,
    "delivery": 0.05,
}

SAAS_CATEGORY_WEIGHTS = {
    "value_proposition": 0.25,
    "conversion": 0.35,
    "trust": 0.25,
    "product_evidence": 0.15,
}

COMMERCIAL_TYPES = {
    PageType.HOME,
    PageType.PRICING,
    PageType.FEATURE,
    PageType.USE_CASE,
    PageType.INDUSTRY,
    PageType.INTEGRATION,
    PageType.COMPARISON,
    PageType.ALTERNATIVE,
    PageType.TEMPLATE,
    PageType.FREE_TOOL,
}


def _issue(
    code: str,
    category: str,
    severity: Severity,
    title: str,
    explanation: str,
    recommendation: str,
    *,
    evidence: dict[str, Any] | None = None,
    penalty: float = 0,
    impact: Impact = Impact.MEDIUM,
    effort: Effort = Effort.MEDIUM,
    confidence: float = 1.0,
    direct_ranking_factor: bool | None = None,
) -> Issue:
    return Issue(
        code=code,
        category=category,
        severity=severity,
        title=title,
        explanation=explanation,
        recommendation=recommendation,
        evidence=evidence or {},
        penalty=penalty,
        impact=impact,
        effort=effort,
        confidence=confidence,
        direct_ranking_factor=direct_ranking_factor,
    )


def detect_issues(parsed: ParsedPage, requested_url: str, final_url: str) -> list[Issue]:
    sections = parsed.sections
    fetch = sections["fetch"]
    metadata = sections["metadata"]
    indexability = sections["indexability"]
    headings = sections["headings"]
    content = sections["content"]
    links = sections["links"]
    images = sections["images"]
    social = sections["social"]
    structured = sections["structured_data"]
    international = sections["international"]
    mobile = sections["mobile"]
    saas = sections["saas"]
    page_type = parsed.page_type
    issues: list[Issue] = []

    status_code = fetch["status_code"]
    if not 200 <= status_code < 300:
        issues.append(
            _issue(
                "http.non_success_status",
                "indexability",
                Severity.CRITICAL,
                f"Page returned HTTP {status_code}",
                "Search engines may not index a URL that does not return a successful status.",
                "Return the intended page with HTTP 200, or use a correct permanent redirect/removal status.",
                evidence={"status_code": status_code},
                penalty=100,
                impact=Impact.HIGH,
                effort=Effort.MEDIUM,
                direct_ranking_factor=True,
            )
        )
    redirects = fetch["redirects"]
    if len(redirects) >= 3:
        issues.append(
            _issue(
                "http.long_redirect_chain",
                "technical",
                Severity.MEDIUM,
                "Long redirect chain",
                "Multiple hops delay crawling and users and make migrations harder to reason about.",
                "Point internal links and the first redirect directly at the final canonical URL.",
                evidence={"redirect_count": len(redirects), "chain": redirects},
                penalty=15,
                impact=Impact.MEDIUM,
                effort=Effort.LOW,
            )
        )
    if urlsplit(requested_url).scheme == "https" and urlsplit(final_url).scheme == "http":
        issues.append(
            _issue(
                "http.https_downgrade",
                "technical",
                Severity.HIGH,
                "HTTPS request downgrades to HTTP",
                "The redirect removes transport security.",
                "Keep every redirect hop and the final page on HTTPS.",
                penalty=40,
                impact=Impact.HIGH,
                effort=Effort.MEDIUM,
            )
        )
    elif urlsplit(final_url).scheme != "https":
        issues.append(
            _issue(
                "http.no_https",
                "technical",
                Severity.HIGH,
                "Page is not served over HTTPS",
                "HTTPS protects users and is a baseline requirement for modern SaaS acquisition pages.",
                "Serve the site over HTTPS and permanently redirect HTTP URLs to HTTPS.",
                penalty=35,
                impact=Impact.HIGH,
                effort=Effort.MEDIUM,
            )
        )

    if indexability["noindex"]:
        severity = Severity.CRITICAL if page_type in COMMERCIAL_TYPES else Severity.HIGH
        issues.append(
            _issue(
                "indexability.noindex",
                "indexability",
                severity,
                "Page declares noindex",
                "The page asks compliant search engines not to include it in search results.",
                "Remove noindex only if this URL is intended to attract organic traffic; otherwise document the intentional exclusion.",
                evidence={
                    "robots_meta": indexability["robots_meta"],
                    "x_robots_tag": indexability["x_robots_tag"],
                },
                penalty=100,
                impact=Impact.HIGH,
                effort=Effort.LOW,
                direct_ranking_factor=True,
            )
        )
    canonical_count = indexability["canonical_count"]
    if canonical_count > 1:
        issues.append(
            _issue(
                "canonical.multiple",
                "indexability",
                Severity.HIGH,
                "Multiple canonical declarations",
                "Conflicting canonical hints can cause search engines to choose an unexpected URL.",
                "Emit one consistent canonical URL across HTML, HTTP headers, internal links, and sitemaps.",
                evidence={"canonical_urls": metadata["canonical_urls"]},
                penalty=35,
                impact=Impact.HIGH,
                effort=Effort.LOW,
            )
        )
    elif canonical_count == 0 and page_type not in {PageType.LOGIN, PageType.LEGAL}:
        issues.append(
            _issue(
                "canonical.missing",
                "indexability",
                Severity.LOW,
                "No canonical hint found",
                "A canonical is not mandatory, but it helps consolidate duplicate URL variants common in campaign and programmatic SaaS pages.",
                "Add a self-referencing absolute canonical to indexable pages and keep it aligned with sitemaps and internal links.",
                penalty=8,
                impact=Impact.MEDIUM,
                effort=Effort.LOW,
                confidence=0.85,
            )
        )
    elif canonical_count == 1:
        canonical = metadata["canonical_urls"][0]
        if urlsplit(canonical).hostname != urlsplit(final_url).hostname:
            issues.append(
                _issue(
                    "canonical.cross_domain",
                    "indexability",
                    Severity.HIGH,
                    "Canonical points to another hostname",
                    "The page is asking search engines to consolidate its signals into another domain.",
                    "Verify that the cross-domain canonical is intentional; otherwise point it to the preferred URL on this site.",
                    evidence={"canonical": canonical},
                    penalty=45,
                    impact=Impact.HIGH,
                    effort=Effort.LOW,
                )
            )
        elif not indexability["canonical_is_self"]:
            issues.append(
                _issue(
                    "canonical.non_self",
                    "indexability",
                    Severity.INFO,
                    "Canonical differs from fetched URL",
                    "This may be intentional consolidation, but it means the analyzed URL is not the preferred version.",
                    "Confirm the target is indexable, equivalent, and used consistently in internal links and sitemaps.",
                    evidence={"canonical": canonical, "final_url": final_url},
                    impact=Impact.LOW,
                    effort=Effort.LOW,
                )
            )

    title = metadata["title"]
    if not title:
        issues.append(
            _issue(
                "title.missing",
                "on_page",
                Severity.HIGH,
                "Title element is missing",
                "A descriptive title helps users and search engines identify the page.",
                "Write a unique title that clearly communicates the page topic and product context.",
                penalty=45,
                impact=Impact.HIGH,
                effort=Effort.LOW,
            )
        )
    else:
        title_length = metadata["title_characters"]
        if title_length < 15:
            issues.append(
                _issue(
                    "title.very_short",
                    "on_page",
                    Severity.LOW,
                    "Title may be too generic",
                    "Very short titles often omit the specific search intent or product context.",
                    "Make the title uniquely descriptive without padding it to a fixed character target.",
                    evidence={"characters": title_length, "title": title},
                    penalty=8,
                    impact=Impact.MEDIUM,
                    effort=Effort.LOW,
                    confidence=0.75,
                )
            )
        elif title_length > 70:
            issues.append(
                _issue(
                    "title.preview_risk",
                    "on_page",
                    Severity.INFO,
                    "Title may truncate in some search layouts",
                    "Google has no fixed title length limit, but long title links are truncated to fit the device.",
                    "Front-load the distinguishing intent and benefit; shorten only if the title becomes clearer.",
                    evidence={"characters": title_length, "title": title},
                    impact=Impact.LOW,
                    effort=Effort.LOW,
                    confidence=0.65,
                )
            )

    description = metadata["description"]
    if not description and page_type not in {PageType.LOGIN, PageType.LEGAL}:
        issues.append(
            _issue(
                "description.missing",
                "on_page",
                Severity.MEDIUM,
                "Meta description is missing",
                "Search engines can generate snippets from content, but a unique description gives a useful page-specific pitch when selected.",
                "Add a concise, accurate summary with the page's differentiator and next step.",
                penalty=18,
                impact=Impact.MEDIUM,
                effort=Effort.LOW,
            )
        )
    elif description and len(description) > 180:
        issues.append(
            _issue(
                "description.preview_risk",
                "on_page",
                Severity.INFO,
                "Description may truncate in some search layouts",
                "There is no fixed meta-description limit; snippets are truncated to fit the result and query.",
                "Keep the most useful and differentiating information early rather than chasing a fixed character count.",
                evidence={"characters": len(description)},
                impact=Impact.LOW,
                effort=Effort.LOW,
                confidence=0.65,
            )
        )
    if metadata["description_count"] > 1:
        issues.append(
            _issue(
                "description.multiple",
                "on_page",
                Severity.MEDIUM,
                "Multiple meta descriptions",
                "Multiple declarations create ambiguity about the intended snippet description.",
                "Render exactly one page-specific meta description.",
                evidence={"count": metadata["description_count"]},
                penalty=12,
                impact=Impact.MEDIUM,
                effort=Effort.LOW,
            )
        )

    h1_count = headings["counts"]["h1"]
    if h1_count == 0:
        issues.append(
            _issue(
                "headings.h1_missing",
                "on_page",
                Severity.MEDIUM,
                "No H1 heading found",
                "A clear primary heading helps users understand the page and provides a stable semantic outline.",
                "Add one visible, descriptive primary heading aligned with the page's intent.",
                penalty=20,
                impact=Impact.MEDIUM,
                effort=Effort.LOW,
            )
        )
    if headings["empty"]:
        issues.append(
            _issue(
                "headings.empty",
                "on_page",
                Severity.MEDIUM,
                "Empty heading elements found",
                "Empty headings add noise to the document outline and assistive navigation.",
                "Remove empty heading tags or give them meaningful visible text.",
                evidence={"count": headings["empty"]},
                penalty=10,
                impact=Impact.LOW,
                effort=Effort.LOW,
            )
        )
    if headings["skipped_levels"]:
        issues.append(
            _issue(
                "headings.skipped_levels",
                "on_page",
                Severity.LOW,
                "Heading levels are skipped",
                "A logical hierarchy makes long feature, guide, and comparison pages easier to navigate.",
                "Use heading levels to represent nested sections rather than visual size.",
                evidence={"transitions": headings["skipped_levels"][:10]},
                penalty=6,
                impact=Impact.LOW,
                effort=Effort.LOW,
            )
        )

    word_count = content["word_count"]
    minimum_words = {
        PageType.BLOG: 350,
        PageType.GUIDE: 500,
        PageType.GLOSSARY: 250,
        PageType.FEATURE: 180,
        PageType.USE_CASE: 220,
        PageType.INDUSTRY: 220,
        PageType.COMPARISON: 350,
        PageType.ALTERNATIVE: 350,
        PageType.CASE_STUDY: 250,
        PageType.HOME: 120,
    }.get(page_type, 80)
    if word_count < 30 and fetch["content_bytes"] > 10_000:
        issues.append(
            _issue(
                "content.javascript_shell",
                "content",
                Severity.HIGH,
                "Initial HTML contains very little readable content",
                "The page may depend on client-side rendering. Google can render JavaScript, but rendering is delayed and many other crawlers cannot.",
                "Server-render or pre-render critical headings, copy, links, and structured data; verify rendered HTML separately.",
                evidence={"word_count": word_count, "html_bytes": fetch["content_bytes"]},
                penalty=45,
                impact=Impact.HIGH,
                effort=Effort.HIGH,
                confidence=0.85,
            )
        )
    elif word_count < minimum_words and page_type not in {PageType.LOGIN, PageType.LEGAL}:
        issues.append(
            _issue(
                "content.possibly_thin",
                "content",
                Severity.MEDIUM if page_type in COMMERCIAL_TYPES else Severity.LOW,
                "Page may not fully satisfy its inferred intent",
                "Word count is not a ranking target, but sparse pages often omit proof, examples, objections, or task-specific detail.",
                "Review the search intent and add only useful evidence, workflows, examples, FAQs, or original data—not filler.",
                evidence={
                    "word_count": word_count,
                    "contextual_review_threshold": minimum_words,
                    "page_type": page_type.value,
                },
                penalty=18 if page_type in COMMERCIAL_TYPES else 8,
                impact=Impact.MEDIUM,
                effort=Effort.MEDIUM,
                confidence=0.65,
            )
        )

    internal_count = links["internal"]["count"]
    if internal_count == 0 and page_type not in {PageType.LOGIN, PageType.LEGAL}:
        issues.append(
            _issue(
                "links.no_internal_links",
                "links",
                Severity.HIGH,
                "No crawlable internal links",
                "Important pages should connect users and crawlers to related content and product journeys.",
                "Add contextual HTML links to the next useful pages, using descriptive anchor text.",
                penalty=45,
                impact=Impact.HIGH,
                effort=Effort.LOW,
            )
        )
    if links["empty_anchor"]:
        issues.append(
            _issue(
                "links.empty_anchor",
                "links",
                Severity.MEDIUM,
                "Links without usable anchor text",
                "Empty link text gives users and crawlers little context about the destination.",
                "Add concise visible text or meaningful alt text for linked images.",
                evidence={"count": links["empty_anchor"]},
                penalty=min(20, links["empty_anchor"] * 3),
                impact=Impact.MEDIUM,
                effort=Effort.LOW,
            )
        )
    if links["generic_anchor"] >= 3:
        issues.append(
            _issue(
                "links.generic_anchors",
                "links",
                Severity.LOW,
                "Repeated generic anchor text",
                "Labels such as 'learn more' are less useful out of context than destination-specific anchors.",
                "Rename important contextual links so the anchor describes what the user will find.",
                evidence={"count": links["generic_anchor"]},
                penalty=min(10, links["generic_anchor"]),
                impact=Impact.LOW,
                effort=Effort.LOW,
                confidence=0.8,
            )
        )

    if images["missing_alt_attribute"]:
        issues.append(
            _issue(
                "images.alt_missing",
                "media_social",
                Severity.MEDIUM,
                "Images are missing alt attributes",
                'A missing alt attribute prevents an explicit text alternative. Decorative images should use alt="".',
                "Write useful alt text for informative images and explicit empty alt text for purely decorative images.",
                evidence={
                    "count": images["missing_alt_attribute"],
                    "samples": images["issue_samples"]["missing_alt"],
                },
                penalty=min(35, 8 + images["missing_alt_attribute"] * 3),
                impact=Impact.MEDIUM,
                effort=Effort.LOW,
            )
        )
    if images["linked_without_alt"]:
        issues.append(
            _issue(
                "images.linked_without_alt",
                "links",
                Severity.HIGH,
                "Linked images lack usable text",
                "For an image-only link, alt text functions as anchor text and an accessible name.",
                "Give each linked image a concise alt value describing the link destination.",
                evidence={"count": images["linked_without_alt"]},
                penalty=min(25, images["linked_without_alt"] * 8),
                impact=Impact.HIGH,
                effort=Effort.LOW,
            )
        )
    if images["total"] >= 3 and images["missing_dimensions"] / images["total"] > 0.5:
        issues.append(
            _issue(
                "images.dimensions_missing",
                "delivery",
                Severity.LOW,
                "Most images lack explicit dimensions",
                "Reserved image space helps reduce layout shifts, though CSS aspect-ratio can also provide it.",
                "Set intrinsic width/height or a stable CSS aspect-ratio and verify CLS in field or browser data.",
                evidence={
                    "missing": images["missing_dimensions"],
                    "total": images["total"],
                },
                penalty=8,
                impact=Impact.MEDIUM,
                effort=Effort.MEDIUM,
                confidence=0.7,
            )
        )

    if page_type in COMMERCIAL_TYPES and not social["open_graph_complete"]:
        issues.append(
            _issue(
                "social.open_graph_incomplete",
                "social",
                Severity.LOW,
                "Open Graph preview is incomplete",
                "Commercial SaaS pages are frequently shared in chat and social channels; incomplete metadata reduces preview control.",
                "Provide page-specific og:title, og:description, og:image, and og:url values.",
                evidence={"present": sorted(social["open_graph"])},
                penalty=10,
                impact=Impact.LOW,
                effort=Effort.LOW,
                direct_ranking_factor=False,
            )
        )

    if structured["invalid_blocks"]:
        issues.append(
            _issue(
                "schema.invalid_jsonld",
                "structured_data",
                Severity.HIGH,
                "Invalid JSON-LD structured data",
                "Malformed JSON-LD cannot be interpreted reliably and can make rich-result markup ineligible.",
                "Fix every JSON parse error, then validate the deployed URL with a schema-specific testing tool.",
                evidence={"errors": structured["errors"]},
                penalty=min(60, 25 + structured["invalid_blocks"] * 10),
                impact=Impact.HIGH,
                effort=Effort.LOW,
            )
        )
    schema_types = set(structured["types"])
    if page_type is PageType.HOME and not schema_types & {
        "Organization",
        "Corporation",
        "WebSite",
        "SoftwareApplication",
        "WebApplication",
    }:
        issues.append(
            _issue(
                "schema.home_entity_missing",
                "structured_data",
                Severity.LOW,
                "No organization or software entity JSON-LD detected",
                "Accurate entity markup can help search systems understand the company and software represented on the page.",
                "Add truthful Organization and, where applicable, SoftwareApplication/WebApplication JSON-LD matching visible content.",
                penalty=12,
                impact=Impact.MEDIUM,
                effort=Effort.MEDIUM,
                confidence=0.8,
            )
        )

    if not international["html_lang"]:
        issues.append(
            _issue(
                "international.lang_missing",
                "technical",
                Severity.LOW,
                "HTML language is missing",
                "A valid lang attribute helps browsers and assistive technologies interpret pronunciation and language.",
                "Set the html lang attribute to the primary language of this page.",
                penalty=5,
                impact=Impact.LOW,
                effort=Effort.LOW,
            )
        )
    if not mobile["responsive_viewport"]:
        issues.append(
            _issue(
                "mobile.viewport_missing",
                "technical",
                Severity.HIGH,
                "Responsive viewport declaration is missing",
                "Without a device-width viewport, mobile rendering and usability can be severely degraded.",
                "Add a standard responsive viewport meta tag and test the page at mobile widths.",
                evidence={"viewport": mobile["viewport"]},
                penalty=35,
                impact=Impact.HIGH,
                effort=Effort.LOW,
            )
        )
    if not mobile["charset"]:
        issues.append(
            _issue(
                "html.charset_missing",
                "technical",
                Severity.LOW,
                "Character encoding is not declared",
                "An explicit UTF-8 declaration avoids inconsistent text decoding.",
                "Declare UTF-8 early in the document head or the Content-Type response header.",
                penalty=4,
                impact=Impact.LOW,
                effort=Effort.LOW,
            )
        )

    ttfb_ms = fetch["timing"]["ttfb_ms"]
    if ttfb_ms > 1_800:
        issues.append(
            _issue(
                "delivery.ttfb_very_slow",
                "delivery",
                Severity.HIGH,
                "Very slow server response in this probe",
                "This single probe exceeded the poor TTFB boundary used by PageSpeed as an experimental diagnostic; it is not field data.",
                "Measure across regions and real users, then optimize caching, application work, database queries, and CDN routing.",
                evidence={"ttfb_ms": ttfb_ms},
                penalty=45,
                impact=Impact.HIGH,
                effort=Effort.HIGH,
                confidence=0.65,
            )
        )
    elif ttfb_ms > 800:
        issues.append(
            _issue(
                "delivery.ttfb_slow",
                "delivery",
                Severity.MEDIUM,
                "Slow server response in this probe",
                "The measured TTFB exceeded 800 ms, but one server-side request is not representative field data.",
                "Repeat measurements and inspect CDN caching, backend latency, and geography before prioritizing a fix.",
                evidence={"ttfb_ms": ttfb_ms},
                penalty=18,
                impact=Impact.MEDIUM,
                effort=Effort.HIGH,
                confidence=0.6,
            )
        )
    if fetch["content_bytes"] > 100_000 and not fetch["delivery"]["content_encoding"]:
        issues.append(
            _issue(
                "delivery.html_uncompressed",
                "delivery",
                Severity.MEDIUM,
                "Large HTML response appears uncompressed",
                "Transferring a large text response without Brotli or gzip wastes bandwidth.",
                "Enable Brotli or gzip for HTML and verify the Content-Encoding header at the CDN/origin.",
                evidence={"content_bytes": fetch["content_bytes"]},
                penalty=15,
                impact=Impact.MEDIUM,
                effort=Effort.LOW,
                confidence=0.9,
            )
        )

    # SaaS acquisition/conversion diagnostics are deliberately outside core SEO weights.
    value = saas["value_proposition"]
    conversion = saas["conversion"]
    trust = saas["trust"]
    product = saas["product_evidence"]
    if page_type in COMMERCIAL_TYPES and not value["present"]:
        issues.append(
            _issue(
                "saas.value_proposition_unclear",
                "saas_value_proposition",
                Severity.HIGH,
                "No clear primary value proposition detected",
                "A commercial landing page should quickly state what the product helps the intended visitor accomplish.",
                "Write a specific H1 that names the outcome, audience, or use case; validate it with conversion research.",
                evidence={"h1": value["h1"], "page_type": page_type.value},
                penalty=40,
                impact=Impact.HIGH,
                effort=Effort.MEDIUM,
                confidence=0.75,
                direct_ranking_factor=False,
            )
        )
    if page_type in COMMERCIAL_TYPES and not conversion["has_transactional_cta"]:
        issues.append(
            _issue(
                "saas.transactional_cta_missing",
                "saas_conversion",
                Severity.HIGH,
                "No transactional SaaS CTA detected",
                "Organic acquisition pages need a next step such as starting, trying, buying, or requesting a demo.",
                "Add a page-appropriate primary action and a lower-commitment secondary action; measure clicks and qualified conversions.",
                evidence={"detected_cta_groups": conversion["cta_groups"]},
                penalty=35,
                impact=Impact.HIGH,
                effort=Effort.MEDIUM,
                confidence=0.8,
                direct_ranking_factor=False,
            )
        )
    if page_type in COMMERCIAL_TYPES and trust["group_count"] == 0:
        issues.append(
            _issue(
                "saas.proof_missing",
                "saas_trust",
                Severity.MEDIUM,
                "No trust or customer-proof language detected",
                "High-intent visitors often need evidence that the product is credible, secure, and proven.",
                "Add verifiable customer outcomes, relevant security proof, reviews, or case-study links without fabricated claims.",
                penalty=30,
                impact=Impact.HIGH,
                effort=Effort.HIGH,
                confidence=0.7,
                direct_ranking_factor=False,
            )
        )
    if page_type in COMMERCIAL_TYPES and not product["has_product_visual"]:
        issues.append(
            _issue(
                "saas.product_evidence_missing",
                "saas_product_evidence",
                Severity.LOW,
                "No obvious product visual detected",
                "Screenshots or interactive examples can make a software promise concrete, though filenames and alt text are only heuristics.",
                "Show the real product or output near relevant claims and give informative images useful alt text.",
                penalty=20,
                impact=Impact.MEDIUM,
                effort=Effort.MEDIUM,
                confidence=0.55,
                direct_ranking_factor=False,
            )
        )
    if (
        page_type in {PageType.COMPARISON, PageType.ALTERNATIVE}
        and not saas["comparison_table_present"]
    ):
        issues.append(
            _issue(
                "saas.comparison_evidence_missing",
                "saas_product_evidence",
                Severity.MEDIUM,
                "Comparison structure is not evident",
                "Bottom-funnel readers need transparent criteria, trade-offs, and evidence rather than a one-sided sales page.",
                "Add an accessible comparison table or structured criteria, cite evidence, disclose fit differences, and keep facts current.",
                penalty=25,
                impact=Impact.HIGH,
                effort=Effort.HIGH,
                confidence=0.7,
                direct_ranking_factor=False,
            )
        )
    return issues


def score_issues(issues: list[Issue]) -> ScoreBreakdown:
    deductions: dict[str, float] = defaultdict(float)
    for issue in issues:
        if issue.category in SEO_CATEGORY_WEIGHTS:
            deductions[issue.category] += issue.penalty
    categories = {
        category: round(clamp(100 - deductions[category]), 1) for category in SEO_CATEGORY_WEIGHTS
    }
    overall = round(
        sum(categories[category] * weight for category, weight in SEO_CATEGORY_WEIGHTS.items()),
        1,
    )
    grade, rating = grade_for(overall)
    return ScoreBreakdown(
        overall=overall,
        grade=grade,
        rating=rating,
        categories=categories,
        weights=SEO_CATEGORY_WEIGHTS,
    )


def score_saas(issues: list[Issue], page_type: PageType) -> dict[str, Any]:
    mapping = {
        "saas_value_proposition": "value_proposition",
        "saas_conversion": "conversion",
        "saas_trust": "trust",
        "saas_product_evidence": "product_evidence",
    }
    deductions: dict[str, float] = defaultdict(float)
    for issue in issues:
        if issue.category in mapping:
            deductions[mapping[issue.category]] += issue.penalty
    categories = {
        category: round(clamp(100 - deductions[category]), 1) for category in SAAS_CATEGORY_WEIGHTS
    }
    if page_type not in COMMERCIAL_TYPES:
        return {
            "applicable": False,
            "overall": None,
            "grade": None,
            "rating": "not_applicable",
            "categories": categories,
            "weights": SAAS_CATEGORY_WEIGHTS,
            "note": "Conversion maturity is not scored for this inferred page type.",
        }
    overall = round(
        sum(categories[category] * weight for category, weight in SAAS_CATEGORY_WEIGHTS.items()),
        1,
    )
    grade, rating = grade_for(overall)
    return {
        "applicable": True,
        "overall": overall,
        "grade": grade,
        "rating": rating,
        "categories": categories,
        "weights": SAAS_CATEGORY_WEIGHTS,
        "methodology_version": "2026.1",
        "note": "This is an explainable acquisition/conversion heuristic, not a search ranking prediction.",
    }


def recommendations_from_issues(issues: list[Issue]) -> list[Recommendation]:
    impact_score = {Impact.HIGH: 100, Impact.MEDIUM: 65, Impact.LOW: 35}
    effort_factor = {Effort.LOW: 1.0, Effort.MEDIUM: 0.75, Effort.HIGH: 0.5}
    severity_factor = {
        Severity.CRITICAL: 1.0,
        Severity.HIGH: 0.9,
        Severity.MEDIUM: 0.72,
        Severity.LOW: 0.5,
        Severity.INFO: 0.3,
    }
    recommendations: list[Recommendation] = []
    for issue in issues:
        priority = round(
            impact_score[issue.impact]
            * effort_factor[issue.effort]
            * severity_factor[issue.severity]
            * issue.confidence
        )
        recommendations.append(
            Recommendation(
                code=f"fix.{issue.code}",
                priority=int(clamp(priority)),
                impact=issue.impact,
                effort=issue.effort,
                confidence=issue.confidence,
                title=issue.title,
                action=issue.recommendation,
                why=issue.explanation,
                validation=(
                    f"Deploy the change, re-run the analyzer, and verify that `{issue.code}` is resolved; "
                    "for content or conversion changes, also compare first-party search and conversion data."
                ),
                issue_codes=[issue.code],
            )
        )
    return sorted(recommendations, key=lambda item: (-item.priority, item.code))


def apply_scoring(
    parsed: ParsedPage, *, requested_url: str, final_url: str
) -> tuple[list[Issue], ScoreBreakdown, list[Recommendation]]:
    issues = detect_issues(parsed, requested_url, final_url)
    score = score_issues(issues)
    parsed.sections["saas"]["score"] = score_saas(issues, parsed.page_type)
    recommendations = recommendations_from_issues(issues)
    return issues, score, recommendations


def is_duplicate_url(left: str, right: str) -> bool:
    return normalize_url(left) == normalize_url(right)
