# SaaS SEO Analyzer API

A security-first FastAPI service for technical SEO, SaaS acquisition strategy, sampled site crawling, page comparison, and first-party opportunity ranking.

This fork is a ground-up v2 implementation of [KovalDenys1/SEO-Analyzer-API](https://github.com/KovalDenys1/SEO-Analyzer-API). It keeps the original GET endpoints for compatibility while replacing the one-file analyzer with a tested, explainable, asynchronous engine.

## What it does

- Audits status, redirects, indexability, canonical hints, metadata, headings, content, internal links, images, language, mobile setup, social previews, and JSON-LD.
- Classifies SaaS pages such as pricing, feature, use case, industry, integration, template, comparison, alternative, free tool, docs, case study, security, and changelog pages.
- Scores **core SEO health separately from SaaS acquisition/conversion readiness**.
- Produces evidence-backed issues and ranked recommendations with impact, effort, confidence, validation, and affected pages.
- Crawls a bounded site sample while respecting `robots.txt`, discovering XML sitemap indexes, and detecting sampled broken links, exact duplicates, weak internal linking, and potential orphan pages.
- Assesses seven SaaS strategy pillars: commercial foundation, audience/use cases, product-led acquisition, bottom-funnel evaluation, authority, trust, and product enablement.
- Compares up to eight pages without mislabeling the result as a Google ranking.
- Ranks supplied Search Console/conversion rows by traffic and revenue opportunity without inventing external keyword or SERP data.
- Optionally enriches a page with Google PageSpeed Insights v5 lab/field data.

## Safety by default

The service fetches user-supplied URLs, so URL handling is part of the security boundary:

- only HTTP(S) on configured ports;
- credentials in URLs are rejected;
- private, loopback, link-local, multicast, and reserved addresses are rejected;
- every DNS answer and every redirect target is validated;
- the request connects to the validated IP while preserving the public Host/SNI identity, limiting DNS-rebinding exposure;
- proxy environment variables are ignored;
- response time, redirect count, concurrency, and decompressed response size are bounded;
- optional `X-API-Key` authentication;
- bounded TTL/LRU cache and request coalescing.

Private-network access can be enabled for a trusted internal deployment, but it is off by default.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/v1/analyze?url=…` | Full page report; optional PageSpeed and subdomain scope |
| `POST` | `/v1/site-audit` | Bounded robots-aware crawl and SaaS strategy assessment |
| `POST` | `/v1/compare` | Relative SEO/SaaS comparison for 2–8 pages |
| `POST` | `/v1/opportunities` | First-party traffic/revenue opportunity ranking |
| `GET` | `/analyze` | Backwards-compatible original full-analysis shape plus `v2` data |
| `GET` | `/quick-score` | Score, warnings, and top recommendations |
| `GET` | `/metadata` | Metadata, headings, social, and canonical data |
| `GET` | `/healthz`, `/readyz`, `/metrics` | Health, readiness, and Prometheus metrics |

Interactive OpenAPI docs are available at `/docs` and `/redoc`.

## Quick start

Python 3.11–3.14 is supported.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
uvicorn main:app --reload
```

Analyze a page:

```bash
curl --get http://127.0.0.1:8000/v1/analyze \
  --data-urlencode 'url=https://example.com'
```

Audit a site sample:

```bash
curl http://127.0.0.1:8000/v1/site-audit \
  -H 'Content-Type: application/json' \
  -d '{
    "url": "https://example.com",
    "max_pages": 25,
    "max_depth": 3,
    "concurrency": 5,
    "respect_robots": true,
    "use_sitemap": true
  }'
```

If `SEO_API_KEY` is set, add `-H 'X-API-Key: …'` to protected endpoints.

## Docker

The image runs as a non-root user. The Compose example binds only to loopback, drops Linux capabilities, uses a read-only filesystem, and adds a health check.

```bash
cp .env.example .env
docker compose up --build
```

## Configuration

All settings use the `SEO_` prefix. See [`.env.example`](.env.example) for the complete list.

| Variable | Default | Meaning |
|---|---:|---|
| `SEO_API_KEY` | empty | Optional `X-API-Key` shared secret |
| `SEO_FETCH_TIMEOUT_SECONDS` | `12` | Upstream request timeout |
| `SEO_MAX_RESPONSE_BYTES` | `3000000` | Maximum decompressed page/resource body |
| `SEO_MAX_REDIRECTS` | `5` | Redirect budget |
| `SEO_MAX_CONCURRENT_FETCHES` | `8` | Process-wide fetch concurrency |
| `SEO_ALLOW_PRIVATE_HOSTS` | `false` | Permit non-public targets; trusted deployments only |
| `SEO_CACHE_TTL_SECONDS` | `300` | Analysis cache TTL; `0` disables cache |
| `SEO_MAX_SITE_PAGES` | `100` | Server-side hard cap for a site audit |
| `SEO_ENABLE_PAGESPEED` | `false` | Permit quota-consuming PageSpeed calls |
| `SEO_PAGESPEED_API_KEY` | empty | Optional Google API key |
| `SEO_CORS_ORIGINS` | empty | Comma-separated browser origins |

## Scores are diagnostics, not promises

The core score is a weighted, fully explainable health summary. Every deduction maps to an issue code and evidence. The SaaS score is a separate page-type-aware acquisition/conversion heuristic. Site strategy maturity measures detected coverage in the bounded sample.

None of these scores predicts a Google position, traffic, revenue, content quality, or rich-result eligibility. The network timer is not LCP/INP/CLS. Browser performance is reported only when PageSpeed is explicitly enabled. See [the scoring methodology](docs/METHODOLOGY.md) for weights and caveats.

## Development

```bash
ruff check .
ruff format --check .
mypy seo_analyzer
pytest --cov --cov-report=term-missing
pip-audit
```

The suite covers URL security, DNS/redirect validation, parsing, page classification, issue scoring, sitemap/robots behavior, crawl aggregation, PageSpeed normalization, API compatibility, auth, and opportunity ranking.

## Documentation

- [API guide](docs/API.md)
- [Scoring methodology](docs/METHODOLOGY.md)
- [SaaS SEO strategy playbook](docs/SAAS_SEO_PLAYBOOK.md)
- [Original-project audit](docs/UPSTREAM_AUDIT.md)
- [Security model](docs/SECURITY.md)
- [Changelog](CHANGELOG.md)

## License and attribution

MIT. The upstream project is copyright Denys Koval; this fork preserves the original license and history. See [LICENSE](LICENSE).
