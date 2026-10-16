# Changelog

All notable changes to this fork are documented here.

## Unreleased

### Fixed

- Client-rendered pages with a small HTML shell, such as a Vite or Create React App `index.html` with an empty `#root`, were reported as thin content with a missing H1 and no internal links, but not as a JavaScript shell, because the shell check required more than 10 KB of HTML. The check now also fires on an empty app mount element, a module script or a `<noscript>` asking for JavaScript, and lists the signals it found in `content.client_render_hints` and the issue evidence.

## 2.1.0 – 2026-10-05

### Added

- `SEO_API_KEYS`: a comma-separated list of additional `X-API-Key` values, accepted alongside `SEO_API_KEY`, so each consumer can hold and rotate its own key.
- Apify Actor in `apify-actor/`: runs the analyzer in-process and returns page, quick-score and site audits as dataset items, charged per page.

### Fixed

- An `X-API-Key` header with non-ASCII characters returned 500; it now returns 401.

## 2.0.0 — 2026-07-22

### Added

- Security-first async fetcher with SSRF controls, DNS pinning, redirect revalidation, response budgets, and bounded concurrency.
- Versioned page analysis with evidence-backed issues, category scores, grades, and prioritized recommendations.
- SaaS page classification, acquisition/conversion readiness scoring, and strategy-pillar assessment.
- Robots-aware sampled site crawler with sitemap-index/gzip support, duplicates, broken-link evidence, internal-authority ranking, and orphan candidates.
- Relative multi-page comparison and first-party Search Console/conversion opportunity ranking.
- Optional Google PageSpeed Insights v5 provider with graceful quota/error handling.
- Typed request/response models, API-key option, CORS allowlist, request IDs, health/readiness routes, and Prometheus metrics.
- Non-root hardened container, loopback-only Compose example, CI, Dependabot, linting, type checking, dependency auditing, and comprehensive tests.
- Detailed methodology, security, SaaS strategy, API, and upstream-audit documentation.

### Changed

- Replaced the arbitrary `100 - 15 × warning count` score with transparent weighted categories.
- Replaced blocking `requests` usage with `httpx.AsyncClient`.
- Kept `/analyze`, `/quick-score`, and `/metadata` as compatibility routes while correcting their documentation/implementation mismatch.
- Treats `alt=""` as a possible valid decorative-image choice instead of always counting it as missing.
- Treats title/description character counts as preview heuristics, not hard search-engine limits.

### Removed

- Unbounded global dictionary cache.
- Full word-density map for every token.
- Claims that a plain HTML fetch measures LCP, CLS, or other browser Core Web Vitals.
