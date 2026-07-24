import pytest
from bs4 import BeautifulSoup

from seo_analyzer.models import PageType
from seo_analyzer.saas import (
    assess_site_strategy,
    classify_page,
    classify_path,
    extract_saas_signals,
)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://x.test/", PageType.HOME),
        ("https://x.test/en", PageType.HOME),
        ("https://x.test/pricing", PageType.PRICING),
        ("https://x.test/features/automation", PageType.FEATURE),
        ("https://x.test/use-cases/sales", PageType.USE_CASE),
        ("https://x.test/industries/finance", PageType.INDUSTRY),
        ("https://x.test/integrations/slack", PageType.INTEGRATION),
        ("https://x.test/compare/acme-vs-beta", PageType.COMPARISON),
        ("https://x.test/beta-alternatives", PageType.ALTERNATIVE),
        ("https://x.test/templates/brief", PageType.TEMPLATE),
        ("https://x.test/tools/roi-calculator", PageType.FREE_TOOL),
        ("https://x.test/blog/post", PageType.BLOG),
        ("https://x.test/guides/automation", PageType.GUIDE),
        ("https://x.test/glossary/mrr", PageType.GLOSSARY),
        ("https://x.test/docs/api", PageType.DOCS),
        ("https://x.test/case-studies/acme", PageType.CASE_STUDY),
        ("https://x.test/security", PageType.SECURITY),
        ("https://x.test/changelog", PageType.CHANGELOG),
        ("https://x.test/about", PageType.ABOUT),
        ("https://x.test/careers", PageType.CAREERS),
        ("https://x.test/privacy", PageType.LEGAL),
        ("https://x.test/login", PageType.LOGIN),
        ("https://x.test/random", PageType.OTHER),
    ],
)
def test_classify_path_catalog(url: str, expected: PageType) -> None:
    assert classify_path(url) is expected


def test_title_can_classify_when_path_is_opaque() -> None:
    result = classify_page("https://x.test/p/123", "Acme vs Beta comparison", "")
    assert result["type"] == PageType.COMPARISON
    assert result["confidence"] < 0.9


def test_explicit_path_wins_over_incidental_title_phrase() -> None:
    result = classify_page(
        "https://x.test/blog/pricing-research", "Pricing strategy comparison", ""
    )
    assert result["type"] == PageType.BLOG
    assert result["confidence"] > 0.9


def test_extract_saas_signals_detects_ctas_trust_forms_and_assets() -> None:
    soup = BeautifulSoup(
        """<html><body><h1>Automate sales work and save time</h1>
        <p>Trusted by customers worldwide. SOC 2, GDPR, 4.9 rating on G2. No credit card.</p>
        <a href='/pricing'>Pricing</a><a href='/integrations/slack'>Slack integration</a>
        <a href='/templates/x'>Template</a><button>Start free</button><button>Book a demo</button>
        <form><input type='email'></form><img src='dashboard.png' alt='Product dashboard'>
        <table><tr><td>Comparison</td></tr></table></body></html>""",
        "html.parser",
    )
    signals = extract_saas_signals(
        soup,
        url="https://x.test/features/automation",
        title="Automation",
        h1_texts=["Automate sales work and save time"],
        visible_text=soup.get_text(" ", strip=True),
        internal_urls=[
            "https://x.test/pricing",
            "https://x.test/integrations/slack",
            "https://x.test/templates/x",
        ],
        schema_types=["AggregateRating"],
    )
    assert signals["page_type"]["type"] == PageType.FEATURE
    assert {"start_free", "demo"} <= set(signals["conversion"]["cta_groups"])
    assert signals["conversion"]["email_capture_forms"] == 1
    assert signals["trust"]["group_count"] >= 3
    assert signals["trust"]["structured_review_data"] is True
    assert signals["product_evidence"]["has_product_visual"] is True
    assert signals["comparison_table_present"] is True
    assert signals["intent_assets_linked"]["pricing"] == 1


def test_site_strategy_maturity_and_guardrail() -> None:
    complete = [
        PageType.HOME,
        PageType.PRICING,
        PageType.FEATURE,
        PageType.USE_CASE,
        PageType.INDUSTRY,
        PageType.INTEGRATION,
        PageType.TEMPLATE,
        PageType.COMPARISON,
        PageType.ALTERNATIVE,
        PageType.BLOG,
        PageType.GUIDE,
        PageType.CASE_STUDY,
        PageType.SECURITY,
        PageType.DOCS,
        PageType.CHANGELOG,
    ]
    result = assess_site_strategy(complete, 100)
    assert result["score"] >= 85
    assert result["maturity"] == "advanced"
    assert "mass-produce" in result["quality_guardrail"]
    sparse = assess_site_strategy([PageType.HOME], 1)
    assert sparse["maturity"] == "foundational"
    assert any(pillar["opportunity"] for pillar in sparse["pillars"].values())
