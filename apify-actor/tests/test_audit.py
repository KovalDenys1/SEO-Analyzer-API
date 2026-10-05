import pytest
from conftest import FakeSite, Ledger
from pydantic import ValidationError
from src.audit import ActorInput, run_audit


def issue_codes(item: dict) -> set[str]:
    return {issue["code"] for issue in item["issues"]}


async def run(site: FakeSite, ledger: Ledger, **raw_input: object) -> object:
    return await run_audit(ActorInput.model_validate(raw_input), site.analyzer, ledger)


async def test_page_mode_emits_one_charged_full_report_per_url(site: FakeSite) -> None:
    ledger = Ledger()
    summary = await run(
        site, ledger, urls=["https://acme.test/", "https://acme.test/pricing"], mode="page"
    )

    assert ledger.events == ["page-audited", "page-audited"]
    home, pricing = ledger.items
    assert (home["type"], home["url"], home["title"], home["status_code"]) == (
        "page",
        "https://acme.test/",
        "Acme home",
        200,
    )
    assert "description.missing" not in issue_codes(home)
    assert "description.missing" in issue_codes(pricing)
    assert pricing["issue_count"] == len(pricing["issues"])
    assert pricing["seo_score"] == pricing["score"]["overall"]
    assert {"links", "content", "recommendations", "saas"} <= set(home)
    assert (summary.audited, summary.failed, summary.stopped_by_budget) == (2, 0, False)


async def test_quick_mode_emits_score_and_top_fixes_without_page_sections(
    site: FakeSite,
) -> None:
    ledger = Ledger()
    await run(site, ledger, urls=["https://acme.test/pricing"], mode="quick")

    assert ledger.events == ["quick-score"]
    (item,) = ledger.items
    assert set(item) == {
        "type",
        "url",
        "title",
        "status_code",
        "page_type",
        "seo_score",
        "seo_grade",
        "saas_score",
        "saas_grade",
        "issue_count",
        "warnings",
        "top_recommendations",
    }
    assert (item["type"], item["title"]) == ("quick", "Acme pricing")
    assert 1 <= len(item["top_recommendations"]) <= 5
    assert all(isinstance(warning, str) for warning in item["warnings"])


async def test_unfetchable_url_becomes_free_error_item_and_run_continues(
    site: FakeSite,
) -> None:
    ledger = Ledger()
    summary = await run(site, ledger, urls=["http://127.0.0.1/", "https://acme.test/"])

    assert ledger.events == [None, "page-audited"]
    error, page = ledger.items
    assert error == {
        "type": "error",
        "url": "http://127.0.0.1/",
        "error": {
            "code": "private_network_blocked",
            "message": error["error"]["message"],
        },
    }
    assert page["url"] == "https://acme.test/"
    assert (summary.audited, summary.failed) == (1, 1)


async def test_unexpected_failure_on_one_url_does_not_stop_the_others(site: FakeSite) -> None:
    ledger = Ledger()
    await run(site, ledger, urls=["https://acme.test/boom", "https://acme.test/"])

    assert ledger.events == [None, "page-audited"]
    assert ledger.items[0]["error"] == {"code": "unexpected_error", "message": "socket exploded"}


async def test_site_mode_reports_a_malformed_start_url_as_free_error_item(
    site: FakeSite,
) -> None:
    ledger = Ledger()
    summary = await run(
        site, ledger, urls=["ftp://acme.test/", "https://acme.test/"], mode="site", maxPages=1
    )

    assert ledger.events == [None, "page-audited", None]
    assert ledger.items[0]["type"] == "error"
    assert ledger.items[0]["error"]["code"] == "invalid_url"
    assert (summary.audited, summary.failed) == (1, 1)


async def test_site_mode_emits_charged_pages_then_one_free_site_summary(
    site: FakeSite,
) -> None:
    ledger = Ledger()
    summary = await run(site, ledger, urls=["https://acme.test/"], mode="site", maxPages=10)

    assert ledger.events == ["page-audited", "page-audited", "page-audited", None]
    *pages, summary_item = ledger.items
    assert [page["url"] for page in pages] == [
        "https://acme.test/",
        "https://acme.test/features",
        "https://acme.test/pricing",
    ]
    assert all(page["type"] == "page" and "issues" in page for page in pages)
    assert pages[2]["crawl"] == {
        "source": "internal_link",
        "depth": 1,
        "inlinks_from_sample": 1,
        "opportunity_score": pages[2]["crawl"]["opportunity_score"],
    }
    assert summary_item["type"] == "site"
    assert summary_item["url"] == "https://acme.test/"
    assert summary_item["pages_audited"] == 3
    assert summary_item["sample"]["pages_audited"] == 3
    assert summary.audited == 3


async def test_site_mode_never_crawls_more_pages_than_the_budget_affords(
    site: FakeSite,
) -> None:
    ledger = Ledger(budget=2)
    summary = await run(site, ledger, urls=["https://acme.test/"], mode="site", maxPages=10)

    assert ledger.events == ["page-audited", "page-audited", None]
    assert ledger.items[-1]["sample"]["max_pages"] == 2
    html_fetches = [path for path in site.fetched_paths if path in {"/", "/pricing", "/features"}]
    assert len(html_fetches) == 2
    assert summary.stopped_by_budget is True


async def test_page_mode_does_not_fetch_urls_the_budget_cannot_pay_for(
    site: FakeSite,
) -> None:
    ledger = Ledger(budget=1)
    summary = await run(site, ledger, urls=["https://acme.test/", "https://acme.test/pricing"])

    assert ledger.events == ["page-audited"]
    assert "/pricing" not in site.fetched_paths
    assert summary.stopped_by_budget is True


def test_input_adds_https_to_bare_domains_and_drops_duplicates() -> None:
    parsed = ActorInput.model_validate(
        {"urls": ["acme.test", "https://acme.test", " acme.test/pricing ", ""]}
    )

    assert parsed.urls == ["https://acme.test", "https://acme.test/pricing"]
    assert (parsed.mode, parsed.max_pages) == ("page", 25)


@pytest.mark.parametrize(
    "raw_input",
    [
        {},
        {"urls": []},
        {"urls": ["  "]},
        {"urls": ["acme.test"], "mode": "deep"},
        {"urls": ["acme.test"], "maxPages": 101},
    ],
)
def test_input_rejects_missing_urls_unknown_mode_and_oversized_page_cap(
    raw_input: dict,
) -> None:
    with pytest.raises(ValidationError):
        ActorInput.model_validate(raw_input)
