import httpx
import pytest
from conftest import OPTIMIZED_HTML, make_fetcher, make_settings
from test_parser_scoring import VITE_SHELL_HTML, make_result

from seo_analyzer.analyzer import Analyzer
from seo_analyzer.fetcher import FetchError
from seo_analyzer.parser import parse_page
from seo_analyzer.scoring import apply_scoring

CLOUDFLARE_CHALLENGE = b"""<!DOCTYPE html><html lang="en-US"><head><title>Just a moment...</title>
<meta name="robots" content="noindex,nofollow"></head><body><div class="main-wrapper">
<noscript>Enable JavaScript and cookies to continue</noscript>
<script src="/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page/v1"></script></div></body></html>"""

PLAIN_FORBIDDEN = b"""<!DOCTYPE html><html lang="en"><head><title>403 Forbidden</title></head>
<body><h1>Forbidden</h1><p>You don't have permission to access this resource.</p></body></html>"""

ARTICLE_ABOUT_CHALLENGES = OPTIMIZED_HTML.replace(
    b"</body>", b"<p>How a security check such as Just a moment pages affects crawlers.</p></body>"
)


async def _analyze(status: int, headers: dict[str, str], body: bytes):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status, headers={"content-type": "text/html; charset=utf-8", **headers}, content=body
        )

    settings = make_settings()
    analyzer = Analyzer(settings, fetcher=make_fetcher(handler, settings=settings))
    try:
        return await analyzer.analyze("https://saas.test/")
    finally:
        await analyzer.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "headers", "body"),
    [
        (403, {"cf-mitigated": "challenge", "server": "cloudflare"}, CLOUDFLARE_CHALLENGE),
        (403, {"server": "cloudflare"}, CLOUDFLARE_CHALLENGE),
        (503, {"server": "cloudflare"}, CLOUDFLARE_CHALLENGE),
        (403, {"x-datadome": "protected"}, PLAIN_FORBIDDEN),
        (405, {"x-amzn-waf-action": "captcha"}, PLAIN_FORBIDDEN),
    ],
)
async def test_bot_protection_challenge_is_an_error_not_a_report(
    status: int, headers: dict[str, str], body: bytes
) -> None:
    with pytest.raises(FetchError) as caught:
        await _analyze(status, headers, body)
    assert caught.value.code == "blocked_by_bot_protection"


@pytest.mark.asyncio
async def test_plain_403_is_still_audited_as_served() -> None:
    report = await _analyze(403, {}, PLAIN_FORBIDDEN)
    assert report.fetch["status_code"] == 403


@pytest.mark.asyncio
async def test_page_mentioning_challenges_is_not_mistaken_for_one() -> None:
    report = await _analyze(200, {"server": "cloudflare"}, ARTICLE_ABOUT_CHALLENGES)
    assert report.score.overall >= 90


def _score(html: bytes, status: int = 200):
    parsed = parse_page(make_result(html, status=status))
    issues, score, recommendations = apply_scoring(
        parsed, requested_url="https://saas.test/", final_url="https://saas.test/"
    )
    return parsed, issues, score, recommendations


def test_javascript_shell_fails_and_leads_the_fixes() -> None:
    parsed, issues, score, recommendations = _score(VITE_SHELL_HTML)
    shell = next(issue for issue in issues if issue.code == "content.javascript_shell")
    assert "empty" in shell.title.lower()
    assert score.overall <= 40
    assert score.grade == "F"
    assert recommendations[0].code == "fix.content.javascript_shell"
    assert parsed.sections["saas"]["score"]["overall"] is None


def test_javascript_shell_symptoms_point_at_the_shell_instead_of_their_own_fix() -> None:
    _, issues, _, recommendations = _score(VITE_SHELL_HTML)
    symptoms = [issue for issue in issues if issue.evidence.get("likely_cause")]
    assert symptoms
    assert all(issue.evidence["likely_cause"] == "content.javascript_shell" for issue in symptoms)
    recommended = {code for rec in recommendations for code in rec.issue_codes}
    assert not recommended & {issue.code for issue in symptoms}


def test_error_status_page_fails_and_leads_with_the_status() -> None:
    noindexed = OPTIMIZED_HTML.replace(
        b"<head>", b'<head><meta name="robots" content="noindex">', 1
    )
    parsed, issues, score, recommendations = _score(noindexed, status=404)
    codes = {issue.code for issue in issues}
    assert score.overall <= 20
    assert score.grade == "F"
    assert recommendations[0].code == "fix.http.non_success_status"
    assert "indexability.noindex" not in codes
    assert parsed.sections["saas"]["score"]["overall"] is None


def test_noindex_on_a_working_page_is_still_reported() -> None:
    noindexed = OPTIMIZED_HTML.replace(
        b"<head>", b'<head><meta name="robots" content="noindex">', 1
    )
    _, issues, _, _ = _score(noindexed)
    assert "indexability.noindex" in {issue.code for issue in issues}


def test_healthy_page_is_not_capped() -> None:
    parsed, _, score, _ = _score(OPTIMIZED_HTML)
    assert score.overall >= 90
    assert parsed.sections["saas"]["score"]["overall"] >= 90
