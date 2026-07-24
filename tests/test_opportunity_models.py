import pytest
from pydantic import ValidationError

from seo_analyzer.models import CompareRequest, OpportunityRequest, SiteAuditRequest
from seo_analyzer.opportunity import rank_opportunities


def test_opportunity_ranking_uses_first_party_metrics() -> None:
    request = OpportunityRequest.model_validate(
        {
            "model": "balanced",
            "currency": "eur",
            "pages": [
                {
                    "url": "https://x.test/pricing",
                    "impressions": 10_000,
                    "clicks": 300,
                    "average_position": 6,
                    "conversions": 30,
                    "conversion_value": 9_000,
                    "business_value": 5,
                },
                {
                    "url": "https://x.test/blog/post",
                    "impressions": 30_000,
                    "clicks": 1_000,
                    "average_position": 9,
                    "conversions": 5,
                    "conversion_value": 200,
                    "business_value": 2,
                },
                {
                    "url": "https://x.test/new",
                    "impressions": 0,
                    "clicks": 0,
                    "business_value": 3,
                },
            ],
        }
    )
    result = rank_opportunities(request)
    assert result["currency"] == "EUR"
    assert [page["rank"] for page in result["pages"]] == [1, 2, 3]
    assert result["pages"][0]["url"] == "https://x.test/pricing"
    assert result["pages"][0]["estimated_incremental_conversion_value"] > 0
    assert all(0 <= page["opportunity_score"] <= 100 for page in result["pages"])
    assert "does not query" in result["assumptions"][0]


def test_opportunity_target_ctr_and_models() -> None:
    base = {
        "target_ctr": 0.1,
        "pages": [
            {"url": "https://x.test/a", "impressions": 100, "clicks": 2},
            {"url": "https://x.test/b", "impressions": 200, "clicks": 50},
        ],
    }
    for model in ("traffic", "revenue"):
        result = rank_opportunities(OpportunityRequest.model_validate(base | {"model": model}))
        assert result["model"] == model
        assert result["pages"][0]["assumed_target_ctr"] == 0.1
    assert result["pages"][1]["estimated_incremental_clicks"] == 0


def test_request_models_reject_unsafe_shapes() -> None:
    with pytest.raises(ValidationError):
        CompareRequest(urls=["https://x.test", "https://x.test"])
    with pytest.raises(ValidationError):
        SiteAuditRequest(url="https://x.test", max_pages=999)
    with pytest.raises(ValidationError):
        OpportunityRequest.model_validate({"pages": [{"url": "x", "impressions": -1}]})
    with pytest.raises(ValidationError):
        OpportunityRequest.model_validate(
            {"pages": [{"url": "https://x.test", "impressions": 1, "clicks": 2}]}
        )
    with pytest.raises(ValidationError):
        OpportunityRequest.model_validate(
            {
                "pages": [
                    {"url": "https://x.test"},
                    {"url": "https://x.test/#duplicate"},
                ]
            }
        )
    with pytest.raises(ValidationError):
        OpportunityRequest.model_validate({"currency": "12$", "pages": [{"url": "https://x.test"}]})
    with pytest.raises(ValidationError):
        SiteAuditRequest(url="file:///etc/passwd")
