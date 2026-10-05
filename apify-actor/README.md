# SEO Audit with Evidence, Ranked Fixes & SaaS Score

Give it a URL and get an explainable technical SEO audit as JSON. Every point taken off the score maps to an issue code with the evidence that triggered it, and every issue comes with a ranked fix: what to change, why, expected impact, effort, confidence and how to check that the fix worked.

It fetches plain HTML over HTTP. No browser, no proxy, no third-party SEO database, so a page takes about a second and costs cents.

## What you get

- **Two separate scores, 0–100 with a letter grade.** Core SEO health across eight weighted categories, and SaaS acquisition and conversion readiness (value proposition, call to action, trust, product evidence).
- **Issues with evidence.** Code, category, severity, score penalty and the data that triggered it.
- **Fixes in priority order.** Action, reason, impact, effort, confidence and a validation step for each.
- **Fetch and indexability.** Status, redirect chain, robots directives, canonical consistency.
- **On-page.** Title, description, heading outline, content statistics and top terms, internal and external links, image alt and dimension coverage.
- **Social and structured data.** Open Graph, Twitter card, JSON-LD inventory, language and mobile signals.
- **Page type detection for SaaS sites.** Pricing, feature, use case, integration, comparison, alternative, docs, case study and more.
- **Site-level findings in Site audit mode.** Broken internal links, exact duplicate titles, descriptions and content, orphan candidates, the most linked pages and coverage of seven SaaS strategy pillars.

## Modes

| Mode | Use it for | Items in the dataset | Charged as |
|---|---|---|---|
| `page` | A full report for each URL | one `page` item per URL | `page-audited` |
| `quick` | Scoring long URL lists, lead qualification | one `quick` item per URL | `quick-score` |
| `site` | A bounded crawl of a whole site | one `page` item per crawled page, then one `site` summary | `page-audited` per page, summary free |

A URL that cannot be fetched (DNS failure, timeout, not HTML, blocked by the target) becomes an `error` item and is not charged.

## Input

```json
{
  "urls": ["https://example.com"],
  "mode": "site",
  "maxPages": 25,
  "maxDepth": 3,
  "useSitemap": true,
  "respectRobots": true,
  "includeSubdomains": false
}
```

| Field | Type | Default | Notes |
|---|---|---|---|
| `urls` | array of strings | – | Required. Up to 1,000. `example.com` is read as `https://example.com`. In `site` mode each URL starts its own crawl. |
| `mode` | `page`, `quick`, `site` | `page` | See the table above. |
| `maxPages` | integer 1–100 | `25` | `site` mode: pages fetched and charged per start URL. |
| `maxDepth` | integer 0–8 | `3` | `site` mode: link depth from the start URL. Sitemap URLs are sampled regardless of depth. |
| `useSitemap` | boolean | `true` | `site` mode: read robots.txt and XML sitemaps. |
| `respectRobots` | boolean | `true` | `site` mode: skip disallowed pages. |
| `includeSubdomains` | boolean | `false` | Count subdomains as the same site. |

## Output

Every item has `type`, `url` and, when a page was fetched, `title`, `status_code`, `seo_score`, `seo_grade`, `saas_score`, `saas_grade` and `issue_count`, so the Overview table works across modes.

### `quick` item

Real output for `https://example.com`, recommendations shortened to the first of five:

```json
{
  "type": "quick",
  "url": "https://example.com/",
  "title": "Example Domain",
  "status_code": 200,
  "seo_score": 77.8,
  "seo_grade": "C",
  "saas_score": 67.2,
  "saas_grade": "D",
  "issue_count": 12,
  "page_type": { "type": "home", "confidence": 1.0, "evidence": ["root path"] },
  "warnings": [
    "No canonical hint found",
    "Title may be too generic",
    "Meta description is missing",
    "No H1 heading found",
    "Page may not fully satisfy its inferred intent",
    "No crawlable internal links",
    "Open Graph preview is incomplete",
    "No organization or software entity JSON-LD detected",
    "No clear primary value proposition detected",
    "No transactional SaaS CTA detected",
    "No trust or customer-proof language detected",
    "No obvious product visual detected"
  ],
  "top_recommendations": [
    {
      "code": "fix.links.no_internal_links",
      "priority": 90,
      "impact": "high",
      "effort": "low",
      "confidence": 1.0,
      "title": "No crawlable internal links",
      "action": "Add contextual HTML links to the next useful pages, using descriptive anchor text.",
      "why": "Important pages should connect users and crawlers to related content and product journeys.",
      "validation": "Deploy the change, re-run the analyzer, and verify that `links.no_internal_links` is resolved; for content or conversion changes, also compare first-party search and conversion data.",
      "affected_pages": 1,
      "issue_codes": ["links.no_internal_links"]
    }
  ]
}
```

### `page` item

The headline fields plus the full report. Real output for `https://example.com`, shortened where marked with `…`:

```json
{
  "type": "page",
  "url": "https://example.com/",
  "title": "Example Domain",
  "status_code": 200,
  "seo_score": 77.8,
  "seo_grade": "C",
  "saas_score": 67.2,
  "saas_grade": "D",
  "issue_count": 12,
  "schema_version": "2.0",
  "requested_url": "https://example.com/",
  "final_url": "https://example.com/",
  "page_type": { "type": "home", "confidence": 1.0, "evidence": ["root path"] },
  "indexability": {
    "indexable": true,
    "status_allows_indexing": true,
    "noindex": false,
    "robots_meta": [],
    "googlebot_meta": [],
    "x_robots_tag": null,
    "canonical": null,
    "canonical_count": 0,
    "canonical_is_self": false
  },
  "score": {
    "overall": 77.8,
    "grade": "C",
    "rating": "fair",
    "categories": {
      "indexability": 92.0,
      "on_page": 54.0,
      "content": 82.0,
      "links": 55.0,
      "technical": 100.0,
      "structured_data": 88.0,
      "media_social": 90.0,
      "delivery": 100.0
    },
    "weights": {
      "indexability": 0.2,
      "on_page": 0.2,
      "content": 0.2,
      "links": 0.15,
      "technical": 0.1,
      "structured_data": 0.05,
      "media_social": 0.05,
      "delivery": 0.05
    },
    "methodology_version": "2026.1"
  },
  "issues": [
    {
      "code": "description.missing",
      "category": "on_page",
      "severity": "medium",
      "title": "Meta description is missing",
      "explanation": "Search engines can generate snippets from content, but a unique description gives a useful page-specific pitch when selected.",
      "recommendation": "Add a concise, accurate summary with the page's differentiator and next step.",
      "evidence": {},
      "penalty": 18.0,
      "impact": "medium",
      "effort": "low",
      "confidence": 1.0,
      "direct_ranking_factor": null
    },
    "… 11 more"
  ],
  "recommendations": ["… 12 ranked fixes, same shape as in the quick item"],
  "…": "also: analyzed_at, fetch, metadata, headings, content, links, images, social, structured_data, international, mobile, performance, saas, limitations"
}
```

In `site` mode each `page` item also carries `crawl`: `{ "source": "internal_link", "depth": 1, "inlinks_from_sample": 4, "opportunity_score": 10 }`.

### `site` item

One per start URL, after its pages. Real output for a four-page site, shortened:

```json
{
  "type": "site",
  "url": "https://overtidskalkulator.no/",
  "seo_score": 99.6,
  "seo_grade": "A",
  "pages_audited": 4,
  "sample": {
    "max_pages": 25,
    "pages_audited": 4,
    "urls_discovered": 4,
    "sitemap_urls": 4,
    "blocked_by_robots": 0,
    "fetch_failures": 0,
    "page_budget_reached": false,
    "truncated": false
  },
  "saas_strategy": {
    "score": 4.8,
    "maturity": "foundational",
    "page_type_distribution": { "home": 2, "other": 2 },
    "pillars": { "commercial_foundation": { "score": 33.3, "opportunity": "Build or make discoverable homepage, pricing, and feature/product pages; each page must add unique user value." }, "…": "6 more pillars" }
  },
  "architecture": { "broken_internal_edges": [], "broken_pages": [], "orphan_candidates": [], "top_linked_pages": ["…"] },
  "duplicates": { "titles": [], "descriptions": [], "exact_content_signatures": [] },
  "issues": [
    {
      "code": "saas.transactional_cta_missing",
      "title": "No transactional SaaS CTA detected",
      "category": "saas_conversion",
      "severity": "high",
      "count": 2,
      "urls": ["https://overtidskalkulator.no/", "https://overtidskalkulator.no/om"]
    },
    "… 5 more"
  ],
  "recommendations": ["… 13 ranked fixes with affected URLs"],
  "…": "also: schema_version, audited_at, site, requested_url, score, pages, rankings, technical_assets, crawl_errors, out_of_scope_redirects, robots_blocked_urls, limitations"
}
```

### `error` item

```json
{
  "type": "error",
  "url": "https://no-such-host.invalid",
  "error": { "code": "dns_resolution_failed", "message": "DNS resolution failed for no-such-host.invalid" }
}
```

## Pricing

Pay per event. There is no monthly rental, and platform usage is included in the event price.

| Event | Price | When |
|---|---|---|
| `page-audited` | $0.02 | Each page returned as a `page` item, in `page` and `site` modes |
| `quick-score` | $0.005 | Each URL returned as a `quick` item |
| Actor start | $0.00005 | Once per run |

Not charged: `error` items and the `site` summary.

| Run | Cost |
|---|---|
| Full report for one page | $0.02 |
| Site audit, 25 pages | $0.50 |
| Site audit, 100 pages | $2.00 |
| Quick score for 1,000 URLs | $5.00 |

If you set a maximum charge for the run, the Actor checks it before fetching: a site crawl is capped at the number of pages the limit pays for, and a URL list stops at the last URL it covers.

## What it does not do

- It does not execute JavaScript. Content that only appears after client-side rendering is not seen.
- It does not predict Google positions, traffic or revenue. Scores are diagnostics, and the weights and limitations are returned with them.
- It has no keyword, backlink or SERP database.
- It does not measure Core Web Vitals. Timing covers the HTML response only.
- It does not rotate proxies or solve bot challenges. Sites that block data-centre traffic or need a login return an `error` item.
- A site audit is a bounded sample of up to 100 pages per start URL, not an exhaustive crawl.

## How it crawls

- Identifies itself as `SaaSSEOAnalyzer/2.0` and follows robots.txt rules for the `SaaSSEOAnalyzer` user agent unless `respectRobots` is off.
- Up to 5 concurrent requests per site, 12 seconds per request, 3 MB per response, 5 redirects.
- Refuses private, loopback and link-local addresses, including after redirects.

## FAQ

**How is the score calculated?** Eight categories (indexability, on-page, content, links, technical, structured data, media and social, delivery) are scored 0–100 and combined with the weights returned in `score.weights`. Each issue lists its `penalty`. The method is documented in [METHODOLOGY.md](https://github.com/KovalDenys1/SEO-Analyzer-API/blob/main/docs/METHODOLOGY.md).

**Why is the SaaS score separate?** A page can be technically clean and still give a visitor no reason to sign up. Mixing the two would hide both. `saas_score` is `null` on pages where it does not apply, such as legal or contact pages.

**Can I audit sites I do not own?** Yes, any public page. Keep `respectRobots` on for them.

**Does a redirected URL count twice?** No. A URL is one item, reported under its final address with the redirect chain in `fetch.redirects`.

**Is the analyzer open source?** Yes, MIT: [KovalDenys1/SEO-Analyzer-API](https://github.com/KovalDenys1/SEO-Analyzer-API). Bug reports go to the Issues tab here or on GitHub.
