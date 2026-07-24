import copy

from conftest import OPTIMIZED_HTML, POOR_HTML, PUBLIC_IP

from seo_analyzer.fetcher import FetchResult, RedirectHop
from seo_analyzer.models import PageType
from seo_analyzer.parser import ParsedPage, parse_page
from seo_analyzer.scoring import (
    apply_scoring,
    detect_issues,
    is_duplicate_url,
    recommendations_from_issues,
    score_issues,
    score_saas,
)


def make_result(
    html: bytes,
    *,
    url: str = "https://saas.test/",
    status: int = 200,
    headers: dict[str, str] | None = None,
    ttfb_ms: int = 120,
) -> FetchResult:
    response_headers = {"content-type": "text/html; charset=utf-8", "content-encoding": "br"}
    response_headers.update(headers or {})
    return FetchResult(
        requested_url=url,
        final_url=url,
        status_code=status,
        headers=response_headers,
        content=html,
        encoding="utf-8",
        content_type="text/html",
        http_version="HTTP/2",
        resolved_ip=PUBLIC_IP,
        redirects=[],
        ttfb_ms=ttfb_ms,
        download_ms=10,
        total_ms=ttfb_ms + 10,
    )


def test_parser_extracts_rich_page_sections() -> None:
    parsed = parse_page(make_result(OPTIMIZED_HTML))
    sections = parsed.sections
    assert parsed.page_type is PageType.HOME
    assert sections["metadata"]["title"].startswith("Acme Workflow")
    assert sections["metadata"]["canonical"] == "https://saas.test/"
    assert sections["headings"]["counts"]["h1"] == 1
    assert sections["headings"]["counts"]["h2"] == 2
    assert sections["content"]["word_count"] > 120
    assert sections["content"]["top_terms"]
    assert sections["links"]["internal"]["count"] >= 7
    assert sections["links"]["external"]["count"] == 1
    assert sections["links"]["nofollow"] == 1
    assert sections["images"]["with_descriptive_alt"] == 1
    assert sections["images"]["missing_dimensions"] == 0
    assert sections["structured_data"]["invalid_blocks"] == 0
    assert {"Organization", "SoftwareApplication", "AggregateRating"} <= set(
        sections["structured_data"]["types"]
    )
    assert sections["social"]["open_graph_complete"] is True
    assert sections["international"]["has_x_default"] is True
    assert sections["mobile"]["responsive_viewport"] is True
    assert sections["saas"]["conversion"]["has_transactional_cta"] is True
    assert sections["saas"]["trust"]["group_count"] >= 2
    assert len(parsed.text_signature) == 64


def test_parser_distinguishes_empty_alt_and_invalid_jsonld() -> None:
    html = b"""<html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>
    <title>A sufficiently descriptive page title</title><script type='application/ld+json'></script>
    <script type='application/ld+json'>{bad}</script></head><body><h1>Useful heading text</h1>
    <img src='/decorative.svg' alt=''><img src='/missing.png'><a href='/x'><img src='/linked.png' alt=''></a>
    <a href='mailto:a@example.com'>mail</a><a href='#section'>fragment</a></body></html>"""
    parsed = parse_page(make_result(html, url="https://saas.test/features/x"))
    images = parsed.sections["images"]
    assert images["total"] == 3
    assert images["empty_alt_decorative_candidates"] == 2
    assert images["missing_alt_attribute"] == 1
    assert images["linked_without_alt"] == 1
    assert parsed.sections["structured_data"]["invalid_blocks"] == 2
    assert parsed.sections["links"]["non_web_or_fragment_skipped"] == 2


def test_linked_decorative_image_uses_sibling_link_text() -> None:
    html = b"""<html><body><a href='/feature'><img src='/icon.svg' alt=''>Feature details</a>
    <a href='http://[:::]'>invalid</a></body></html>"""
    parsed = parse_page(make_result(html))
    assert parsed.sections["images"]["linked_without_alt"] == 0
    assert parsed.sections["links"]["unique"] == 1


def test_excessive_jsonld_nodes_are_reported_not_raised() -> None:
    import seo_analyzer.parser as parser_module

    original_limit = parser_module.MAX_JSONLD_NODES
    parser_module.MAX_JSONLD_NODES = 2
    try:
        html = b"""<html><body><script type='application/ld+json'>
        {"@type":"Thing","nested":{"one":{"two":true}}}
        </script></body></html>"""
        parsed = parse_page(make_result(html))
    finally:
        parser_module.MAX_JSONLD_NODES = original_limit
    assert parsed.sections["structured_data"]["invalid_blocks"] == 1
    assert "node analysis limit" in parsed.sections["structured_data"]["errors"][0]["error"]


def test_optimized_page_scores_high_and_separates_social() -> None:
    parsed = parse_page(make_result(OPTIMIZED_HTML))
    issues, score, recommendations = apply_scoring(
        parsed, requested_url="https://saas.test/", final_url="https://saas.test/"
    )
    codes = {issue.code for issue in issues}
    assert score.overall >= 90
    assert score.grade == "A"
    assert not codes & {
        "title.missing",
        "description.missing",
        "headings.h1_missing",
        "links.no_internal_links",
        "saas.transactional_cta_missing",
    }
    assert parsed.sections["saas"]["score"]["applicable"] is True
    assert parsed.sections["saas"]["score"]["overall"] >= 90
    assert recommendations == sorted(recommendations, key=lambda item: (-item.priority, item.code))


def test_poor_page_emits_evidence_backed_issues() -> None:
    html = POOR_HTML.replace(b"</body>", b"<script>" + b"x" * 12_000 + b"</script></body>")
    parsed = parse_page(make_result(html, headers={"content-type": "text/html"}))
    issues, score, recommendations = apply_scoring(
        parsed, requested_url="https://saas.test/", final_url="https://saas.test/"
    )
    codes = {issue.code for issue in issues}
    assert {
        "canonical.missing",
        "title.very_short",
        "description.missing",
        "headings.h1_missing",
        "content.javascript_shell",
        "links.empty_anchor",
        "links.generic_anchors",
        "images.alt_missing",
        "images.linked_without_alt",
        "schema.invalid_jsonld",
        "international.lang_missing",
        "mobile.viewport_missing",
        "html.charset_missing",
        "saas.transactional_cta_missing",
    } <= codes
    assert score.overall < 70
    assert recommendations[0].priority >= recommendations[-1].priority


def _optimized_parsed() -> ParsedPage:
    return parse_page(make_result(OPTIMIZED_HTML))


def test_issue_engine_critical_and_operational_branches() -> None:
    parsed = copy.deepcopy(_optimized_parsed())
    sections = parsed.sections
    sections["fetch"]["status_code"] = 503
    sections["fetch"]["redirects"] = [
        {"status_code": 301},
        {"status_code": 302},
        {"status_code": 302},
    ]
    sections["fetch"]["content_bytes"] = 200_000
    sections["fetch"]["delivery"]["content_encoding"] = None
    sections["fetch"]["timing"]["ttfb_ms"] = 2_000
    sections["indexability"].update(
        {"noindex": True, "canonical_count": 2, "x_robots_tag": "noindex"}
    )
    sections["metadata"].update(
        {
            "title": "",
            "title_characters": 0,
            "description": "",
            "description_count": 2,
            "canonical_urls": ["https://saas.test/a", "https://saas.test/b"],
        }
    )
    sections["headings"]["counts"]["h1"] = 0
    sections["headings"]["empty"] = 1
    sections["headings"]["skipped_levels"] = [{"from": 1, "to": 3}]
    sections["content"]["word_count"] = 0
    sections["links"]["internal"]["count"] = 0
    sections["links"].update({"empty_anchor": 2, "generic_anchor": 3})
    sections["images"].update(
        {
            "total": 3,
            "missing_alt_attribute": 2,
            "linked_without_alt": 1,
            "missing_dimensions": 3,
        }
    )
    sections["images"]["issue_samples"]["missing_alt"] = ["/a.png"]
    sections["structured_data"].update(
        {"invalid_blocks": 1, "errors": [{"error": "bad"}], "types": []}
    )
    sections["international"]["html_lang"] = None
    sections["mobile"].update({"responsive_viewport": False, "viewport": None, "charset": None})
    sections["saas"]["value_proposition"].update({"present": False, "h1": ""})
    sections["saas"]["conversion"].update({"has_transactional_cta": False, "cta_groups": {}})
    sections["saas"]["trust"]["group_count"] = 0
    sections["saas"]["product_evidence"]["has_product_visual"] = False

    codes = {
        issue.code for issue in detect_issues(parsed, "https://saas.test/", "https://saas.test/")
    }
    assert {
        "http.non_success_status",
        "http.long_redirect_chain",
        "indexability.noindex",
        "canonical.multiple",
        "title.missing",
        "description.multiple",
        "headings.empty",
        "headings.skipped_levels",
        "images.dimensions_missing",
        "schema.home_entity_missing",
        "delivery.ttfb_very_slow",
        "delivery.html_uncompressed",
        "saas.value_proposition_unclear",
        "saas.proof_missing",
    } <= codes


def test_issue_engine_preview_canonical_ttfb_and_comparison_branches() -> None:
    parsed = copy.deepcopy(_optimized_parsed())
    parsed.page_type = PageType.COMPARISON
    sections = parsed.sections
    sections["metadata"].update(
        {
            "title": "A" * 80,
            "title_characters": 80,
            "description": "D" * 200,
            "description_count": 1,
            "canonical_urls": ["https://competitor.test/page"],
        }
    )
    sections["indexability"].update({"canonical_count": 1, "canonical_is_self": False})
    sections["fetch"]["timing"]["ttfb_ms"] = 900
    sections["content"]["word_count"] = 100
    sections["saas"]["comparison_table_present"] = False
    issues = detect_issues(parsed, "https://saas.test/page", "http://saas.test/page")
    codes = {issue.code for issue in issues}
    assert {
        "http.https_downgrade",
        "canonical.cross_domain",
        "title.preview_risk",
        "description.preview_risk",
        "content.possibly_thin",
        "delivery.ttfb_slow",
        "saas.comparison_evidence_missing",
    } <= codes

    parsed.sections["metadata"]["canonical_urls"] = ["https://saas.test/preferred"]
    issues = detect_issues(parsed, "https://saas.test/page", "https://saas.test/page")
    assert "canonical.non_self" in {issue.code for issue in issues}


def test_score_helpers_and_noncommercial_saas() -> None:
    parsed = _optimized_parsed()
    parsed.page_type = PageType.DOCS
    issues = detect_issues(parsed, "https://saas.test/docs", "https://saas.test/docs")
    saas = score_saas(issues, PageType.DOCS)
    assert saas["applicable"] is False
    assert saas["overall"] is None
    score = score_issues(issues)
    assert 0 <= score.overall <= 100
    recs = recommendations_from_issues(issues)
    assert all(0 <= recommendation.priority <= 100 for recommendation in recs)
    assert is_duplicate_url("https://x.test/a#x", "https://x.test/a")


def test_fetch_result_text_falls_back_for_unknown_encoding() -> None:
    result = make_result("Привет".encode(), headers={})
    result.encoding = "does-not-exist"
    assert result.text == "Привет"
    result.redirects = [RedirectHop("https://a", 301, "https://b")]
    assert result.redirects[0].status_code == 301
