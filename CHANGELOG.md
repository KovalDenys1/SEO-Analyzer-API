# Changelog

All notable changes to this fork are documented here.

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
