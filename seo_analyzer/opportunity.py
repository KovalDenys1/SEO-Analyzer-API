from typing import Any

from seo_analyzer.models import OpportunityInput, OpportunityRequest
from seo_analyzer.utils import clamp, utc_now_iso


def _expected_ctr(position: float | None) -> float:
    """Conservative planning heuristic, deliberately not presented as an industry benchmark."""

    if position is None:
        return 0.05
    if position <= 1.5:
        return 0.25
    if position <= 3:
        return 0.15
    if position <= 5:
        return 0.08
    if position <= 10:
        return 0.04
    if position <= 20:
        return 0.02
    return 0.01


def _page_metrics(page: OpportunityInput, target_ctr: float | None) -> dict[str, Any]:
    actual_ctr = page.clicks / page.impressions if page.impressions else 0
    assumed_target = target_ctr or _expected_ctr(page.average_position)
    incremental_clicks = max(0.0, page.impressions * assumed_target - page.clicks)
    conversion_rate = page.conversions / page.clicks if page.clicks else 0
    value_per_conversion = page.conversion_value / page.conversions if page.conversions else 0
    estimated_value = incremental_clicks * conversion_rate * value_per_conversion
    position_leverage = 1.0
    if page.average_position is not None:
        if 4 <= page.average_position <= 20:
            position_leverage = 1.25
        elif page.average_position > 50:
            position_leverage = 0.5
    return {
        "url": page.url,
        "inputs": page.model_dump(mode="json"),
        "actual_ctr": round(actual_ctr, 5),
        "assumed_target_ctr": round(assumed_target, 5),
        "estimated_incremental_clicks": round(incremental_clicks, 1),
        "observed_conversion_rate": round(conversion_rate, 5),
        "observed_value_per_conversion": round(value_per_conversion, 2),
        "estimated_incremental_conversion_value": round(estimated_value, 2),
        "position_leverage": position_leverage,
        "business_weight": page.business_value / 5,
        "data_quality": {
            "has_impressions": page.impressions > 0,
            "has_position": page.average_position is not None,
            "has_conversion_rate": page.clicks > 0 and page.conversions > 0,
            "has_conversion_value": page.conversions > 0 and page.conversion_value > 0,
        },
    }


def rank_opportunities(request: OpportunityRequest) -> dict[str, Any]:
    pages = [_page_metrics(page, request.target_ctr) for page in request.pages]
    max_clicks = max((page["estimated_incremental_clicks"] for page in pages), default=0) or 1
    max_value = (
        max((page["estimated_incremental_conversion_value"] for page in pages), default=0) or 1
    )
    max_impressions = max((page["inputs"]["impressions"] for page in pages), default=0) or 1

    weights = {
        "balanced": {"traffic": 0.45, "revenue": 0.35, "business": 0.20},
        "traffic": {"traffic": 0.70, "revenue": 0.10, "business": 0.20},
        "revenue": {"traffic": 0.20, "revenue": 0.60, "business": 0.20},
    }[request.model]
    for page in pages:
        traffic_signal = (page["estimated_incremental_clicks"] / max_clicks) * 0.75 + (
            page["inputs"]["impressions"] / max_impressions
        ) * 0.25
        revenue_signal = page["estimated_incremental_conversion_value"] / max_value
        score = (
            traffic_signal * weights["traffic"]
            + revenue_signal * weights["revenue"]
            + page["business_weight"] * weights["business"]
        ) * page["position_leverage"]
        quality = page["data_quality"]
        confidence = 0.35
        confidence += 0.2 if quality["has_impressions"] else 0
        confidence += 0.15 if quality["has_position"] else 0
        confidence += 0.15 if quality["has_conversion_rate"] else 0
        confidence += 0.15 if quality["has_conversion_value"] else 0
        page["opportunity_score"] = round(clamp(score * 100))
        page["confidence"] = round(min(1.0, confidence), 2)
    pages.sort(
        key=lambda page: (
            -page["opportunity_score"],
            -page["estimated_incremental_clicks"],
            page["url"],
        )
    )
    for rank, page in enumerate(pages, 1):
        page["rank"] = rank
    return {
        "schema_version": "2.0",
        "ranked_at": utc_now_iso(),
        "model": request.model,
        "currency": request.currency.upper(),
        "weights": weights,
        "pages": pages,
        "assumptions": [
            "This endpoint ranks only the first-party rows supplied by the caller; it does not query or estimate Google rankings.",
            "When target_ctr is omitted, a conservative position-based planning heuristic is used, not an external CTR benchmark.",
            "Incremental clicks and value are scenarios, not forecasts. Validate changes against Search Console, analytics, qualified conversions, and revenue.",
            "Scores are normalized within this request, so they are not comparable across unrelated batches.",
        ],
    }
