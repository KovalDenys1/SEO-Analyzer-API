from typing import Any

import httpx

from seo_analyzer.config import Settings


class PageSpeedClient:
    ENDPOINT = "https://pagespeedonline.googleapis.com/pagespeedonline/v5/runPagespeed"

    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.pagespeed_timeout_seconds),
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def analyze(self, url: str, strategy: str = "mobile") -> dict[str, Any]:
        if not self.settings.enable_pagespeed:
            return {
                "status": "disabled",
                "provider": "Google PageSpeed Insights API v5",
                "reason": "Set SEO_ENABLE_PAGESPEED=true to allow quota-consuming browser analysis.",
            }
        params: list[tuple[str, str | int | float | bool | None]] = [
            ("url", url),
            ("strategy", strategy),
            ("category", "PERFORMANCE"),
            ("category", "ACCESSIBILITY"),
            ("category", "BEST_PRACTICES"),
            ("category", "SEO"),
        ]
        if self.settings.pagespeed_api_key:
            params.append(("key", self.settings.pagespeed_api_key.get_secret_value()))
        try:
            response = await self._client.get(self.ENDPOINT, params=httpx.QueryParams(params))
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            return {
                "status": "error",
                "provider": "Google PageSpeed Insights API v5",
                "reason": f"PageSpeed API returned HTTP {exc.response.status_code}",
            }
        except httpx.TimeoutException:
            return {
                "status": "error",
                "provider": "Google PageSpeed Insights API v5",
                "reason": "PageSpeed API request timed out",
            }
        except httpx.RequestError:
            return {
                "status": "error",
                "provider": "Google PageSpeed Insights API v5",
                "reason": "PageSpeed API request failed",
            }
        except ValueError:
            return {
                "status": "error",
                "provider": "Google PageSpeed Insights API v5",
                "reason": "PageSpeed API returned invalid JSON",
            }
        lighthouse = data.get("lighthouseResult", {})
        categories = {
            key: round(float(value.get("score", 0)) * 100)
            for key, value in lighthouse.get("categories", {}).items()
            if value.get("score") is not None
        }
        audits = lighthouse.get("audits", {})
        lab_metrics = {}
        for audit_id in (
            "first-contentful-paint",
            "largest-contentful-paint",
            "cumulative-layout-shift",
            "speed-index",
            "total-blocking-time",
            "interactive",
            "server-response-time",
        ):
            audit = audits.get(audit_id)
            if not audit:
                continue
            lab_metrics[audit_id] = {
                "numeric_value": audit.get("numericValue"),
                "numeric_unit": audit.get("numericUnit"),
                "display_value": audit.get("displayValue"),
                "score": audit.get("score"),
            }
        opportunities = []
        for audit_id, audit in audits.items():
            details = audit.get("details") or {}
            savings_ms = details.get("overallSavingsMs", 0) or 0
            savings_bytes = details.get("overallSavingsBytes", 0) or 0
            score = audit.get("score")
            if (score is not None and score < 0.9) and (savings_ms or savings_bytes):
                opportunities.append(
                    {
                        "id": audit_id,
                        "title": audit.get("title"),
                        "display_value": audit.get("displayValue"),
                        "score": score,
                        "estimated_savings_ms": round(savings_ms),
                        "estimated_savings_bytes": round(savings_bytes),
                    }
                )
        opportunities.sort(
            key=lambda item: (item["estimated_savings_ms"], item["estimated_savings_bytes"]),
            reverse=True,
        )
        return {
            "status": "complete",
            "provider": "Google PageSpeed Insights API v5",
            "strategy": strategy,
            "analysis_timestamp": lighthouse.get("fetchTime"),
            "lighthouse_version": lighthouse.get("lighthouseVersion"),
            "categories": categories,
            "lab_metrics": lab_metrics,
            "field": _extract_field_data(data.get("loadingExperience", {})),
            "origin_field": _extract_field_data(data.get("originLoadingExperience", {})),
            "opportunities": opportunities[:15],
            "notes": [
                "Lab results are a simulated run and can vary.",
                "Field data, when present, represents the trailing real-user collection window and may fall back to origin scope.",
                "Google has announced that CrUX field data will eventually be removed from the PageSpeed API; consumers should tolerate null field data.",
            ],
        }


def _extract_field_data(experience: dict[str, Any]) -> dict[str, Any] | None:
    metrics = experience.get("metrics")
    if not metrics:
        return None
    values = {}
    for metric, details in metrics.items():
        values[metric] = {
            "percentile": details.get("percentile"),
            "category": details.get("category"),
        }
    return {
        "scope_id": experience.get("id"),
        "overall_category": experience.get("overall_category"),
        "metrics": values,
    }
