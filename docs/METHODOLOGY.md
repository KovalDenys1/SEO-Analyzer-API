# Scoring methodology

Methodology version `2026.1` turns observed evidence into a prioritization aid. It deliberately keeps technical/on-page SEO health separate from SaaS acquisition and conversion readiness.

## Design rules

1. Every deduction is attached to an issue code, evidence, explanation and remediation.
2. A missing optional enhancement must not erase the effect of a crawl-blocking failure.
3. Page conversion heuristics do not change the core SEO score.
4. Character counts are preview heuristics, not search-engine limits.
5. A static HTTP probe is not a browser performance test.
6. Site results always disclose sample caps and uncertainty.

These choices follow Google's guidance that there is no secret formula for first place, title links and snippets can be rewritten, and useful people-first content matters more than mechanically satisfying a checklist. See the [SEO Starter Guide](https://developers.google.com/search/docs/fundamentals/seo-starter-guide), [title-link documentation](https://developers.google.com/search/docs/appearance/title-link), and [snippet documentation](https://developers.google.com/search/docs/appearance/snippet).

## Core page score

Each category starts at 100. Applicable issue penalties are summed and the category is clamped to `0–100`:

```text
category score = clamp(100 - sum(issue penalties in category), 0, 100)
overall score  = sum(category score × category weight)
```

| Category | Weight | Representative evidence |
|---|---:|---|
| Indexability | 20% | HTTP status, `noindex`, canonical declarations |
| On-page | 20% | Title, description, H1 and document outline |
| Content | 20% | Main-content volume, static JS shell risk |
| Links | 15% | Crawlable internal links, anchors and page relationships |
| Technical | 10% | HTTPS, redirects, language, viewport and charset |
| Structured data | 5% | JSON-LD syntax and contextual entity hints |
| Media/social | 5% | Image accessibility and delivery evidence; social preview findings are reported without a deduction |
| Delivery | 5% | Probe TTFB and HTML transfer compression |

Penalties express diagnostic severity within a category, not a measured Google ranking-factor coefficient. Multiple related problems can reduce a category to zero but never make it negative.

Open Graph/Twitter completeness is emitted as a SaaS distribution recommendation but intentionally uses the unweighted `social` issue category. It therefore does not reduce core SEO health.

### Grades

| Score | Grade | Rating |
|---:|:---:|---|
| 90–100 | A | excellent |
| 80–89.9 | B | strong |
| 70–79.9 | C | fair |
| 55–69.9 | D | weak |
| below 55 | F | critical |

### Issue semantics

`severity` communicates the consequence of leaving a problem unresolved. `impact`, `effort`, and `confidence` drive prioritization. `direct_ranking_factor` is nullable: `false` explicitly marks conversion-only heuristics, while `null` avoids pretending that every relationship is a documented direct factor.

Examples of high-confidence blockers include a non-success status or `noindex` on an intended acquisition page. Examples of lower-confidence diagnostics include generic anchor prevalence, one slow TTFB probe, or product evidence inferred from image filenames.

An empty `alt=""` is not automatically an error because decorative images should normally have empty alternative text. The parser distinguishes a missing attribute from an explicitly empty one.

## SaaS conversion-readiness score

This score applies only to inferred commercial page types: home, pricing, feature, use case, industry, integration, comparison, alternative, template and free tool.

| Category | Weight | Heuristic evidence |
|---|---:|---|
| Value proposition | 25% | Specific primary heading and benefit language |
| Conversion | 35% | Transactional CTA and lead/signup paths |
| Trust | 25% | Customer proof, review/security/risk-reversal signals |
| Product evidence | 15% | Product screenshots/output and comparison structure |

The formula mirrors the category deduction and weighted-average mechanics of the core score, but only `saas_*` issues participate. A docs, blog or legal page returns `applicable: false` rather than being punished for lacking a sales CTA.

The result is a static-HTML heuristic. It cannot determine visual prominence, factual accuracy, message-market fit, qualified lead quality or actual conversion lift.

## Recommendation priority

Each page issue becomes an actionable recommendation:

```text
priority = impact score × effort factor × severity factor × confidence
```

| Dimension | Values |
|---|---|
| Impact score | high `100`, medium `65`, low `35` |
| Effort factor | low `1.0`, medium `0.75`, high `0.5` |
| Severity factor | critical `1.0`, high `0.9`, medium `0.72`, low `0.5`, info `0.3` |
| Confidence | issue-specific `0–1` |

This naturally puts high-impact, low-effort, high-confidence fixes near the top. It is a queueing model, not expected traffic uplift. Site audits merge the same recommendation code, increase affected-page evidence, retain URL samples and sort by priority.

## Site score and rankings

The site score is a weighted mean over successfully audited pages. Commercially central page types receive greater sample weight: home `2.5`, pricing `2.2`, feature/use-case/industry/comparison/alternative `1.8`, integration/free-tool `1.6`, and other types `1.0`.

Four rankings are returned:

- `seo_health`: page score descending;
- `saas_conversion_readiness`: SaaS score descending where applicable;
- `optimization_opportunity`: diagnostic gap adjusted for page-type importance;
- `internal_authority_in_sample`: incoming links observed in the crawl sample.

None is a SERP ranking. The opportunity score has no search volume, backlinks or business data; use `/v1/opportunities` when first-party metrics are available.

## SaaS strategy maturity

Discovered paths are classified into page types and mapped to seven pillars. A pillar score represents variety of detected relevant types up to a small minimum, and the overall strategy score is the mean of pillar scores.

| Score | Maturity |
|---:|---|
| 85–100 | advanced |
| 65–84.9 | established |
| 40–64.9 | developing |
| below 40 | foundational |

Presence does not prove quality; absence in a capped crawl does not prove that an asset does not exist. A missing pillar is a research prompt, never an instruction to mass-publish pages.

## First-party opportunity ranking

`/v1/opportunities` calculates observed CTR, an assumed target CTR, non-negative scenario clicks, observed conversion rate, value per conversion and scenario incremental value. It combines normalized traffic, revenue and caller-supplied business value according to the selected model, then applies a modest position-leverage heuristic.

Confidence increases only when the row contains impressions, position, observed conversions and conversion value. The fallback CTR curve is explicitly an internal planning heuristic rather than an industry benchmark. Supplying a cohort-specific `target_ctr` is preferable.

## Performance interpretation

The normal report includes connection-level TTFB/download timing from one server-side location. It does not measure LCP, INP or CLS. When PageSpeed is enabled, its lab and available field results are kept distinct. The widely used Core Web Vitals thresholds and 75th-percentile assessment are documented by [web.dev](https://web.dev/articles/defining-core-web-vitals-thresholds); PageSpeed API behavior is documented in the [official v5 guide](https://developers.google.com/speed/docs/insights/v5/get-started).

## Structured-data interpretation

The analyzer parses JSON-LD syntax and inventories `@type` values. It does not claim rich-result eligibility or verify every required/recommended property. Validate production markup against the relevant Google feature documentation and its policies, including the [general structured-data guidelines](https://developers.google.com/search/docs/appearance/structured-data/sd-policies).

## Known limits

- No JavaScript rendering, screenshots, interaction or authenticated crawl.
- No backlink index, keyword database, SERP scraping, log-file analysis or Search Console integration.
- Exact normalized duplicates only; no semantic cannibalization model.
- Heuristic multilingual classification currently focuses on English, Russian and Ukrainian path/copy signals.
- In-memory cache and metrics are process-local.
- Scores can change between methodology versions; persist `methodology_version` with historical reports.
