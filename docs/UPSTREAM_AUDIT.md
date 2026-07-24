# Original-project audit

This document records the baseline observed at upstream commit `0e7a7b6` and the rationale for the v2 fork. It is a technical gap analysis, not criticism of the original author's compact educational implementation.

## Baseline

The upstream application was a single 159-line `main.py` with three analysis endpoints. It extracted a title, meta description/keywords, H1/H2 values, all-word density, image alt counts, same-host links and wall-clock fetch duration. Its score was:

```text
max(0, 100 - 15 × warning count)
```

The runtime was pinned to FastAPI `0.110.0`, Uvicorn `0.27.0`, Requests `2.31.0` and Beautiful Soup `4.12.3` with no automated tests or build pipeline.

## Findings and resolutions

| Area | Baseline limitation | v2 resolution |
|---|---|---|
| URL security | Any supplied URL was passed directly to `requests.get`, permitting access attempts to loopback/private/link-local services and redirect pivots | Public-address validation, credential/scheme/port policy, all-answer DNS checks, validated-IP connection pinning and redirect revalidation |
| Resource control | Response size, redirect count and cache growth were unbounded | Decompressed body budget, redirect/concurrency limits, bounded TTL/LRU cache and in-flight request coalescing |
| Async behavior | Synchronous Requests ran inside web handlers and blocked the server worker | Shared `httpx.AsyncClient`, async endpoints and bounded concurrency |
| HTTP semantics | `raise_for_status()` discarded non-2xx pages that are important audit evidence; most failures became HTTP 400 | Status and redirects retained in the report; stable typed fetch errors use appropriate 4xx/5xx statuses |
| Parsing | No canonical, robots, social, language, viewport, charset, JSON-LD, heading hierarchy, anchor-rel or content-area analysis | Modular parser with explicit sections, capped evidence and limitations |
| Image alt | `alt=""` was treated as missing even though it may correctly mark a decorative image | Missing and intentionally empty attributes are counted separately |
| Link scope | Exact netloc comparison and unnormalized URLs created inconsistent results | Normalized crawl keys, tracking-parameter removal and explicit subdomain scope |
| Score | Every warning cost the same 15 points; the score could not explain category health | Weighted category scores with per-issue evidence, severity, penalty, confidence and methodology version |
| Length rules | Title `>60` and description `>160` were presented as hard failures | Long values are low-confidence preview-risk information; missing/duplicate elements carry the meaningful deductions |
| Performance claims | README advertised LCP/CLS and weighted performance that the implementation did not measure | Static timing is labeled as a single probe; real lab/field data is optional through PageSpeed Insights |
| API contract | README response fields and implementation differed, including canonical, OG, robots and performance fields | Generated OpenAPI matches typed routes; legacy endpoints remain and v2 is explicit |
| SaaS strategy | No page intent, conversion, proof, product-led acquisition or site-level strategy analysis | SaaS page classification, separate conversion score, seven strategy pillars and bounded strategic sitemap sampling |
| Site analysis | Single page only | Robots-aware crawl, sitemap indexes/gzip, sample rankings, exact duplicates, broken edges, possible orphans and issue aggregation |
| Prioritization | Flat warning strings | Impact × effort × severity × confidence recommendations with validation steps |
| First-party data | No way to combine SEO findings with business outcomes | Batch-relative traffic/revenue opportunity endpoint with explicit scenario assumptions |
| Operations | No authentication option, readiness, metrics, request IDs, security headers, CORS policy or hardened container | Optional shared key, observability routes, structured errors, non-root read-only container example and CI |
| Quality assurance | No tests, linting, types, dependency audit or packaging validation | Pytest suite with coverage gate, Ruff, MyPy, pip-audit command, wheel build and container build in CI |

## Deliberately excluded

The fork does not claim capabilities it cannot support with the available evidence:

- Google rank tracking or competitor visibility;
- backlink authority or keyword/search-volume databases;
- semantic content quality, E-E-A-T or factual-truth scores;
- browser rendering in the standard fetch path;
- guaranteed rich-result eligibility;
- traffic/revenue forecasts from HTML alone;
- exhaustive enterprise crawling.

These would require external datasets, browser infrastructure, authenticated first-party connectors or human/product-domain review. The API instead exposes evidence and limitations so those systems can be added without corrupting the meaning of existing scores.

## Compatibility decision

Removing the original endpoints would unnecessarily break consumers. `/analyze`, `/quick-score`, and `/metadata` therefore remain, while `/analyze` includes the canonical v2 report. New development belongs under `/v1`, with `schema_version` and `methodology_version` persisted by clients.
