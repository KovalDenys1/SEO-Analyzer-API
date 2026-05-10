# SEO Analyzer API

A REST API for on-page SEO analysis built with Python and FastAPI. Returns metadata, heading structure, link stats, image alt coverage, keyword density, and a composite score for any public URL.

Available on [RapidAPI](https://rapidapi.com) under the `seo-analyzer` listing.

---

## Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/analyze` | Full analysis — all checks, composite score |
| `GET` | `/quick-score` | Score + top warnings only (faster) |
| `GET` | `/metadata` | Title, description, OG tags, canonical, robots |

### Parameters

| Name | Type | Required | Description |
|---|---|---|---|
| `url` | `string` | Yes | The page to analyze (must be publicly accessible) |

---

## Quick start

```bash
curl "https://your-rapidapi-host/analyze?url=https://example.com" \
  -H "X-RapidAPI-Key: YOUR_KEY" \
  -H "X-RapidAPI-Host: YOUR_HOST"
```

### Response shape

```json
{
  "url": "https://example.com",
  "score": 87,
  "warnings": ["missing_canonical", "images_missing_alt"],
  "meta": {
    "title": "Example Domain",
    "description": "...",
    "canonical": null,
    "robots": "index, follow",
    "og_image": "https://example.com/og.png",
    "lang": "en"
  },
  "headings": [
    { "level": 1, "text": "Example Domain" }
  ],
  "links": {
    "internal": 4,
    "external": 2,
    "dofollow": 5,
    "nofollow": 1,
    "broken": []
  },
  "images": {
    "total": 3,
    "missing_alt": ["https://example.com/hero.png"]
  },
  "keywords": [
    { "term": "example", "count": 12, "density": 0.042 }
  ],
  "performance": {
    "ttfb_ms": 188,
    "lcp_s": 1.8,
    "cls": 0.02
  }
}
```

---

## Running locally

```bash
git clone https://github.com/KovalDenys1/SEO-Analyzer-API.git
cd SEO-Analyzer-API
pip install -r requirements.txt
uvicorn main:app --reload
```

The API will be available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

---

## Score calculation

The composite score (0–100) is weighted across six checks:

| Check | Weight |
|---|---|
| Meta completeness | 25% |
| Heading structure | 15% |
| Link health | 15% |
| Image alt coverage | 15% |
| Keyword presence | 15% |
| Performance (LCP, CLS) | 15% |

---

## Tech stack

- **Python 3.11** + **FastAPI**
- **BeautifulSoup4** for HTML parsing
- **httpx** for async page fetching
- In-memory response cache (TTL 5 min)

---

## License

MIT
