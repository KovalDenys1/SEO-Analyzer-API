<div align="center">

# seo.analyzer

**Analyze any page's SEO in milliseconds.**

Fast, accurate SEO analysis via API. Metadata, headings, links, images, keyword density, and a score — in a single round-trip.

![version](https://img.shields.io/badge/version-v1.4.2-0D9488?style=flat-square)
![build](https://img.shields.io/badge/build-passing-1a7f37?style=flat-square)
![coverage](https://img.shields.io/badge/coverage-96%25-1a7f37?style=flat-square)
![node](https://img.shields.io/badge/node-%E2%89%A518-0969da?style=flat-square)
![license](https://img.shields.io/badge/license-MIT-0969da?style=flat-square)
![downloads](https://img.shields.io/badge/downloads-124k%2Fwk-0969da?style=flat-square)

</div>

A production-grade REST API for on-page SEO analysis. One endpoint, JSON in & JSON out, six checks per page, P95 latency under 200ms across 12 regions.

> ⚡ **Try it without signing up** — the `/v1/quick-score` endpoint accepts 100 requests/day without an API key. Production keys take 30 seconds to set up.

---

## 01 — Quick start

Install the SDK or just `curl` the endpoint directly. The shape of the response is the same either way.

```bash
npm install @seo-analyzer/sdk
export SEO_ANALYZER_KEY="sk_live_..."

# or with curl — no SDK needed
curl https://api.seo-analyzer.dev/v1/analyze \
    -H "Authorization: Bearer $SEO_ANALYZER_KEY" \
    -d '{"url":"https://stripe.com/pricing"}'
```

### Or in your code

```ts
import { seo } from '@seo-analyzer/sdk';

const { score, warnings, meta } = await seo.analyze({
  url: 'https://stripe.com',
  include: ['meta', 'links', 'images'],
});

console.log(score);     // → 87
console.log(warnings);  // → ['missing_canonical', 'lcp_slow']
```

---

## 02 — What it checks

| Feature | Description | Endpoint |
|---|---|---|
| **Meta Analysis** | Title, description, OG/twitter cards, canonical, robots, lang, viewport | `GET /v1/metadata` |
| **Headings outline** | Full H1–H6 outline with depth, order, and accessibility flags | `GET /v1/headings` |
| **Link audit** | Internal vs external, dofollow/nofollow, status codes, broken links | `GET /v1/links` |
| **Image alt check** | Total images, missing alt text, dimensions, lazy-loading hints | `GET /v1/images` |
| **Keyword density** | Top terms, n-grams, stop-word filtered counts and ratios | `GET /v1/keywords` |
| **Load time / Web Vitals** | TTFB, LCP, CLS, INP, render-blocking resources | `GET /v1/performance` |

---

## 03 — Pricing

Pay for what you ship. No seats, no minimums — upgrade when you outgrow Free.

| Plan | Price | Quota | Endpoints | Support |
|---|---|---|---|---|
| **Free** | $0 | 100 / day | `/quick-score` only | Community |
| **Pro** ⭐ | $9 / mo | 5,000 / day | All endpoints | Email · 1 day |
| **Business** | $29 / mo | 50,000 / day | All + `/batch` | SLA · dedicated |

---

## 04 — Architecture

The repo is a small monorepo. Each package can be vendored or installed independently.

```
seo-analyzer/
├── packages/
│   ├── core      // extractors: meta, headings, links, images, perf
│   ├── sdk       // typed client: @seo-analyzer/sdk
│   └── cli       // `npx seo-analyze https://...`
├── apps/
│   ├── api       // public REST API · FastAPI + Python
│   └── dashboard // Next.js · keys, billing, usage
└── infra/        // terraform · 12 regions
```

---

## 05 — Self-hosting

Use the open-source core directly — no API key needed.

```python
from seo_analyzer import analyze

result = await analyze("https://stripe.com/pricing", timeout=5000)
print(result.score)     # → 87
print(result.warnings)  # → ['missing_canonical', 'lcp_slow']
```

---

## 06 — Contributing

PRs welcome. Quick rules:

- Open an issue first for any new endpoint or behavior change
- All extractors must come with golden fixtures (real-world HTML)
- Run tests before pushing: `pytest` / `pnpm test`
- Conventional commits: `feat(api):`, `fix(core):`, `docs:`

---

<div align="center">

Built by [@KovalDenys1](https://github.com/KovalDenys1) · [RapidAPI](https://rapidapi.com) · [Changelog](#)

</div>
