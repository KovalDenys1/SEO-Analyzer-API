# API guide

The API returns diagnostic evidence, not a promise of rankings. The stable v2 surface is under `/v1`; the three unversioned analysis routes preserve the original project contract.

## Conventions

- URL inputs must use HTTP or HTTPS and resolve to an allowed public address.
- JSON timestamps are UTC ISO 8601 values.
- Scores use a `0–100` scale and include a letter grade.
- Every response carries `X-Request-ID`. Supply the same header to correlate client and server logs.
- Analysis responses use `Cache-Control: no-store`.
- When `SEO_API_KEY` is configured, send it as `X-API-Key` to analysis and strategy endpoints.
- Request bodies are limited to 1 MB. A reverse proxy should enforce the same or a smaller limit.

## Errors

Fetch and authorization failures have a stable envelope:

```json
{
  "error": {
    "code": "private_network_blocked",
    "message": "The hostname resolves to a private, loopback, link-local, or reserved address",
    "request_id": "a2c878e2-83d7-43a6-8514-11455cf8f28b"
  }
}
```

Common statuses are:

| Status | Meaning |
|---:|---|
| `401` | Missing or invalid API key |
| `413` | Request or fetched response exceeds a configured budget |
| `415` | The page does not return HTML/XHTML |
| `422` | Invalid input, prohibited target, or insufficient successful comparison pages |
| `502` | DNS, network, redirect, or upstream failure |

FastAPI validation errors use its standard `detail` array. Clients should branch on the HTTP status first and tolerate additional response fields.

## `GET /v1/analyze`

Audits one page.

| Query | Default | Notes |
|---|---:|---|
| `url` | required | Absolute HTTP(S) URL |
| `include_pagespeed` | `false` | Also requires `SEO_ENABLE_PAGESPEED=true` |
| `include_subdomains` | `false` | Treat subdomains as internal when classifying links |

```bash
curl --get http://127.0.0.1:8000/v1/analyze \
  --data-urlencode 'url=https://example.com/pricing' \
  --data 'include_pagespeed=false'
```

The response is divided into stable top-level sections:

| Section | Contents |
|---|---|
| `fetch` | Status, redirect chain, content type/size, HTTP version, resolved IP, TTFB/download timing |
| `indexability` | Robots directives, indexable state, canonical consistency |
| `metadata` | Title, description, canonical declarations and supporting metadata |
| `headings`, `content` | Document outline, word-level summaries, authorship/date hints |
| `links`, `images` | Internal/external link evidence, rel values, anchor quality, alt/dimension coverage |
| `social`, `structured_data` | Open Graph/Twitter hints and syntactic JSON-LD inventory |
| `international`, `mobile` | Language/hreflang and viewport/charset signals |
| `performance` | Static network timing or optional PageSpeed lab/field data |
| `page_type`, `saas` | Inferred SaaS page type and conversion-readiness signals |
| `score`, `issues`, `recommendations` | Explainable scoring, evidence, remediation and validation steps |
| `limitations` | What the static analysis could not establish |

The analyzer does not execute JavaScript. A rendered client-side shell can therefore be reported as thin even when a browser later paints content; this is useful as a rendering-risk signal, not proof of failed indexing.

## `POST /v1/site-audit`

Runs a bounded, same-site crawl and aggregates technical and SaaS strategy findings.

```json
{
  "url": "https://example.com",
  "max_pages": 25,
  "max_depth": 3,
  "concurrency": 5,
  "respect_robots": true,
  "include_subdomains": false,
  "include_query_parameters": false,
  "use_sitemap": true
}
```

Limits enforced by the request model are `1–200` processed URLs, depth `0–8`, and concurrency `1–10`; `SEO_MAX_SITE_PAGES` is an additional server-side cap. Fetch failures and robots-blocked candidates consume this budget so a hostile or unavailable site cannot turn a small audit into unbounded requests. Tracking parameters are removed from crawl keys. Other query parameters are excluded by default to avoid faceted crawl explosions.

The crawler:

1. validates the requested origin;
2. reads `robots.txt` and behaves conservatively on network/5xx failures;
3. discovers declared sitemaps or `/sitemap.xml`, including sitemap indexes and bounded gzip payloads;
4. starts with the requested/root page, then samples sitemap URLs across strategically useful SaaS page types;
5. follows crawlable internal links within depth and page budgets;
6. aggregates issues, exact duplicates, sampled internal authority, broken edges and possible orphans.

Important response fields include:

- `sample`: actual coverage and truncation evidence;
- `technical_assets`: robots/sitemap state without returning an unbounded URL inventory;
- `saas_strategy`: seven-pillar coverage inferred from discovered paths;
- `rankings`: relative SEO health, SaaS readiness, optimization opportunity and sampled internal authority;
- `architecture`: broken edges, failed pages, top-linked pages and orphan candidates;
- `duplicates`: exact normalized title, description and content-signature groups;
- `recommendations`: page-level recommendations aggregated by issue code and affected URLs.

All site rankings are internal audit orderings. They are not Google positions or traffic estimates.

## `POST /v1/compare`

Compares two to eight unique pages with the same analyzer.

```json
{
  "urls": [
    "https://example.com/pricing",
    "https://example.com/features/automation"
  ],
  "include_pagespeed": false
}
```

Pages are ranked by diagnostic SEO health and, where applicable, SaaS conversion readiness. The response also identifies category leaders, common issue codes, individual analyses and fetch failures. At least two pages must succeed.

Use this endpoint to compare templates or cohorts that should meet a common quality bar. Do not interpret it as a competitor visibility or SERP ranking tool: it has no keyword set, backlink index, search volume or Google position data.

## `POST /v1/opportunities`

Ranks one to 500 caller-supplied first-party rows. It is intended for page-level exports from Search Console joined to analytics or revenue data.

```json
{
  "model": "balanced",
  "currency": "USD",
  "pages": [
    {
      "url": "https://example.com/integrations/slack",
      "impressions": 18000,
      "clicks": 420,
      "average_position": 7.4,
      "conversions": 21,
      "conversion_value": 6300,
      "business_value": 5
    }
  ]
}
```

`model` can be `balanced`, `traffic`, or `revenue`. Set `target_ctr` to use your own cohort target; otherwise the service uses a deliberately conservative position-based planning heuristic. Output includes the actual and assumed CTR, scenario clicks/value, data-quality flags, confidence and a batch-relative score.

The scenarios are not forecasts. Scores are normalized inside one request and cannot be compared between unrelated batches.

## Compatibility routes

- `GET /analyze` returns the original fields and embeds the complete v2 report under `v2`.
- `GET /quick-score` returns the score, grade, warnings and top five recommendations.
- `GET /metadata` returns metadata, headings, social and canonical information.

Existing consumers can migrate incrementally, but new integrations should use `/v1/analyze`.

## Operations

- `/healthz` confirms that the process can answer.
- `/readyz` confirms analyzer initialization and reports current cache entries.
- `/metrics` exports route/status counters and route-duration histograms in Prometheus format. URL values and API keys are not metric labels.
- `/docs`, `/redoc`, and `/openapi.json` expose the generated API contract.

Health does not prove that a third-party URL, DNS resolver or PageSpeed API is reachable.
