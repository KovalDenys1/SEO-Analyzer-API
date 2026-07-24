import re
from collections import Counter
from typing import Any
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from seo_analyzer.models import PageType
from seo_analyzer.utils import compact_text

PAGE_TYPE_PATTERNS: list[tuple[PageType, tuple[str, ...]]] = [
    (
        PageType.PRICING,
        (
            r"(?:^|/)(?:pricing|plans?|tariffs?|preise|precios?|ceny|tsiny)(?:/|$)",
            r"(?:цены|тарифы|ціни)",
        ),
    ),
    (PageType.ALTERNATIVE, (r"alternatives?", r"(?:альтернатив|альтернативи)")),
    (
        PageType.COMPARISON,
        (r"(?:^|/)(?:compare|comparison|versus|vs)(?:/|$)", r"\bvs\.?\b", r"сравнен", r"порівнян"),
    ),
    (
        PageType.INTEGRATION,
        (r"integrations?", r"app-directory", r"marketplace/apps", r"интеграц", r"інтеграц"),
    ),
    (PageType.TEMPLATE, (r"templates?", r"шаблон", r"шаблони")),
    (
        PageType.CASE_STUDY,
        (
            r"case-stud(?:y|ies)",
            r"customers?/stories",
            r"success-stor",
            r"истори[ия]-клиент",
            r"історі[яї]-клієнт",
        ),
    ),
    (
        PageType.SECURITY,
        (r"(?:^|/)(?:security|trust|compliance|privacy-center)(?:/|$)", r"безопасност", r"безпек"),
    ),
    (
        PageType.CHANGELOG,
        (
            r"(?:^|/)(?:changelog|releases?|product-updates?|whats-new)(?:/|$)",
            r"обновлен",
            r"оновлен",
        ),
    ),
    (
        PageType.DOCS,
        (
            r"(?:^|/)(?:docs?|documentation|developers?|api-reference|help|support|knowledge-base)(?:/|$)",
            r"документац",
            r"довідк",
        ),
    ),
    (PageType.GLOSSARY, (r"(?:^|/)(?:glossary|dictionary|terms)(?:/|$)", r"глоссар", r"словник")),
    (
        PageType.FREE_TOOL,
        (
            r"(?:^|/)(?:tools?|calculators?|generators?|graders?|checkers?)(?:/|$)",
            r"калькулятор",
            r"генератор",
        ),
    ),
    (PageType.BLOG, (r"(?:^|/)(?:blog|news|insights?)(?:/|$)", r"(?:^|/)блог(?:/|$)")),
    (
        PageType.GUIDE,
        (r"(?:^|/)(?:guides?|resources?|ebooks?|academy|learn)(?:/|$)", r"руководств", r"посібник"),
    ),
    (
        PageType.USE_CASE,
        (
            r"use-?cases?",
            r"workflows?",
            r"solutions?",
            r"(?:^|/)uses(?:/|$)",
            r"сценари",
            r"рішенн",
        ),
    ),
    (
        PageType.INDUSTRY,
        (r"industr(?:y|ies)", r"(?:^|/)(?:for|teams?)/(?!developers?$)", r"отрасл", r"галуз"),
    ),
    (
        PageType.FEATURE,
        (r"(?:^|/)(?:features?|product|platform|capabilities)(?:/|$)", r"функц", r"можливост"),
    ),
    (PageType.ABOUT, (r"(?:^|/)(?:about|company)(?:/|$)", r"о-компании", r"про-компан")),
    (PageType.CAREERS, (r"(?:^|/)(?:careers?|jobs?)(?:/|$)", r"ваканси", r"кар'єр")),
    (
        PageType.LEGAL,
        (r"(?:^|/)(?:legal|terms|privacy|cookies|gdpr)(?:/|$)", r"политика-конф", r"політика-конф"),
    ),
    (
        PageType.LOGIN,
        (
            r"(?:^|/)(?:login|log-in|signin|sign-in|signup|sign-up|register)(?:/|$)",
            r"вход",
            r"реєстрац",
        ),
    ),
]


CTA_PATTERNS: dict[str, tuple[str, ...]] = {
    "start_free": (
        r"get started",
        r"start (?:for )?free",
        r"try (?:it )?free",
        r"free trial",
        r"sign up",
        r"начать бесплатно",
        r"спробувати безкоштовно",
        r"почати безкоштовно",
    ),
    "demo": (r"book (?:a )?demo", r"request (?:a )?demo", r"watch demo", r"демо", r"демонстрац"),
    "contact_sales": (
        r"contact sales",
        r"talk to sales",
        r"speak (?:with|to) sales",
        r"связаться с отделом продаж",
        r"зв'язатися з продажами",
    ),
    "buy": (
        r"buy now",
        r"upgrade",
        r"choose plan",
        r"subscribe",
        r"купить",
        r"придбати",
        r"оформить подписку",
    ),
    "learn": (
        r"learn more",
        r"see how",
        r"explore",
        r"read (?:the )?guide",
        r"узнать больше",
        r"дізнатися більше",
    ),
}

TRUST_TERMS: dict[str, tuple[str, ...]] = {
    "customer_proof": (
        "customers",
        "customer stories",
        "case studies",
        "trusted by",
        "клиенты",
        "клієнти",
    ),
    "reviews": ("reviews", "rating", "g2", "capterra", "trustpilot", "отзывы", "відгуки"),
    "security": (
        "soc 2",
        "iso 27001",
        "gdpr",
        "hipaa",
        "security",
        "encryption",
        "безопасность",
        "безпека",
    ),
    "scale": (
        "million users",
        "teams worldwide",
        "companies trust",
        "enterprise-grade",
        "миллион",
        "мільйон",
    ),
    "risk_reversal": (
        "no credit card",
        "cancel anytime",
        "money-back",
        "без кредитной карты",
        "без картки",
    ),
}

BENEFIT_TERMS = (
    "save time",
    "grow",
    "increase",
    "reduce",
    "automate",
    "faster",
    "simplify",
    "scale",
    "revenue",
    "productivity",
    "эконом",
    "увелич",
    "автоматиз",
    "быстр",
    "зрост",
    "заощад",
    "швидш",
)


def classify_page(url: str, title: str = "", h1: str = "") -> dict[str, Any]:
    path = urlsplit(url).path.lower().rstrip("/") or "/"
    content_text = f"{title.lower()} {h1.lower()}"
    if path == "/" or re.fullmatch(r"/[a-z]{2}(?:-[a-z]{2})?", path):
        return {"type": PageType.HOME.value, "confidence": 1.0, "evidence": ["root path"]}
    # A specific path is stronger evidence than a phrase in a title. Evaluate
    # every path pattern before falling back to copy, otherwise a blog article
    # titled "pricing strategy" can be mistaken for the product pricing page.
    for source, confidence in ((path, 0.92), (content_text, 0.72)):
        for page_type, patterns in PAGE_TYPE_PATTERNS:
            matched = [
                pattern for pattern in patterns if re.search(pattern, source, flags=re.IGNORECASE)
            ]
            if not matched:
                continue
            return {
                "type": page_type.value,
                "confidence": confidence,
                "evidence": [f"matched pattern: {matched[0]}"],
            }
    return {
        "type": PageType.OTHER.value,
        "confidence": 0.35,
        "evidence": ["no known SaaS page pattern"],
    }


def classify_path(url: str) -> PageType:
    return PageType(classify_page(url)["type"])


def extract_saas_signals(
    soup: BeautifulSoup,
    *,
    url: str,
    title: str,
    h1_texts: list[str],
    visible_text: str,
    internal_urls: list[str],
    schema_types: list[str],
) -> dict[str, Any]:
    page_type = classify_page(url, title, h1_texts[0] if h1_texts else "")
    action_labels: list[str] = []
    for element in soup.find_all(["a", "button"]):
        label = compact_text(element.get_text(" ", strip=True), 100)
        if label:
            action_labels.append(label)
    labels_text = "\n".join(action_labels).lower()
    cta_groups: dict[str, list[str]] = {}
    for group, patterns in CTA_PATTERNS.items():
        matches = [
            label
            for label in action_labels
            if any(re.search(pattern, label, flags=re.IGNORECASE) for pattern in patterns)
        ]
        if matches:
            cta_groups[group] = list(dict.fromkeys(matches))[:8]

    lowered_text = visible_text.lower()
    trust_signals = {
        group: [term for term in terms if term in lowered_text][:6]
        for group, terms in TRUST_TERMS.items()
    }
    trust_signals = {group: terms for group, terms in trust_signals.items() if terms}

    linked_page_types = Counter(
        page_type_value.value
        for page_type_value in (classify_path(link) for link in internal_urls)
        if page_type_value is not PageType.OTHER
    )
    primary_h1 = h1_texts[0] if h1_texts else ""
    benefit_terms = [term for term in BENEFIT_TERMS if term in primary_h1.lower()]
    forms = soup.find_all("form")
    email_forms = [
        form
        for form in forms
        if form.find("input", attrs={"type": re.compile("email", re.IGNORECASE)})
    ]
    product_visuals = [
        image
        for image in soup.find_all("img")
        if any(
            term in f"{image.get('alt', '')} {image.get('src', '')}".lower()
            for term in ("screenshot", "dashboard", "interface", "product", "workflow", "app")
        )
    ]
    has_comparison_table = bool(soup.find("table")) or bool(
        re.search(r"(?:compare|comparison|vs\.|versus)", labels_text, re.IGNORECASE)
    )

    return {
        "page_type": page_type,
        "value_proposition": {
            "h1": compact_text(primary_h1, 240),
            "present": len(primary_h1.split()) >= 3,
            "benefit_language": benefit_terms,
        },
        "conversion": {
            "cta_groups": cta_groups,
            "cta_count": sum(len(values) for values in cta_groups.values()),
            "forms": len(forms),
            "email_capture_forms": len(email_forms),
            "has_transactional_cta": any(
                key in cta_groups for key in ("start_free", "demo", "contact_sales", "buy")
            ),
        },
        "trust": {
            "groups": trust_signals,
            "group_count": len(trust_signals),
            "structured_review_data": any(
                schema_type in {"Review", "AggregateRating"} for schema_type in schema_types
            ),
        },
        "product_evidence": {
            "product_visual_count": len(product_visuals),
            "has_product_visual": bool(product_visuals),
        },
        "intent_assets_linked": dict(sorted(linked_page_types.items())),
        "comparison_table_present": has_comparison_table,
        "notes": [
            "SaaS signals measure acquisition and conversion readiness, not direct Google ranking factors.",
            "Static HTML heuristics cannot verify visual prominence, factual quality, or real conversion performance.",
        ],
    }


STRATEGY_PILLARS: dict[str, dict[str, Any]] = {
    "commercial_foundation": {
        "label": "Commercial foundation",
        "types": {PageType.HOME, PageType.PRICING, PageType.FEATURE},
        "minimum": 3,
        "examples": "homepage, pricing, and feature/product pages",
    },
    "audience_and_use_cases": {
        "label": "Audience and use-case demand",
        "types": {PageType.USE_CASE, PageType.INDUSTRY},
        "minimum": 2,
        "examples": "use-case, workflow, team, or industry landing pages",
    },
    "product_led_acquisition": {
        "label": "Product-led acquisition",
        "types": {PageType.INTEGRATION, PageType.TEMPLATE, PageType.FREE_TOOL},
        "minimum": 2,
        "examples": "integrations, templates, marketplaces, or genuinely useful free tools",
    },
    "bottom_funnel": {
        "label": "Bottom-funnel evaluation",
        "types": {PageType.COMPARISON, PageType.ALTERNATIVE, PageType.PRICING},
        "minimum": 2,
        "examples": "honest comparison, alternative, and pricing content",
    },
    "authority_and_education": {
        "label": "Authority and education",
        "types": {PageType.BLOG, PageType.GUIDE, PageType.GLOSSARY},
        "minimum": 2,
        "examples": "guides, original research, blog clusters, or a glossary",
    },
    "proof_and_trust": {
        "label": "Proof and trust",
        "types": {PageType.CASE_STUDY, PageType.SECURITY, PageType.ABOUT},
        "minimum": 2,
        "examples": "case studies, security/trust center, and company identity",
    },
    "product_enablement": {
        "label": "Product enablement",
        "types": {PageType.DOCS, PageType.CHANGELOG},
        "minimum": 2,
        "examples": "crawlable documentation/help and a product changelog",
    },
}


def assess_site_strategy(page_types: list[PageType], total_discovered: int) -> dict[str, Any]:
    counts = Counter(page_type.value for page_type in page_types)
    unique_types = set(page_types)
    pillars: dict[str, Any] = {}
    weighted_score = 0.0
    for pillar_id, definition in STRATEGY_PILLARS.items():
        matched_types = sorted(page_type.value for page_type in definition["types"] & unique_types)
        matched_pages = sum(counts[page_type.value] for page_type in definition["types"])
        coverage = min(100.0, (len(matched_types) / definition["minimum"]) * 100)
        weighted_score += coverage
        pillars[pillar_id] = {
            "label": definition["label"],
            "score": round(coverage, 1),
            "detected_page_types": matched_types,
            "sampled_pages": matched_pages,
            "opportunity": None
            if coverage >= 100
            else f"Build or make discoverable {definition['examples']}; each page must add unique user value.",
        }
    score = round(weighted_score / len(STRATEGY_PILLARS), 1)
    if score >= 85:
        maturity = "advanced"
    elif score >= 65:
        maturity = "established"
    elif score >= 40:
        maturity = "developing"
    else:
        maturity = "foundational"
    return {
        "score": score,
        "maturity": maturity,
        "page_type_distribution": dict(sorted(counts.items())),
        "pillars": pillars,
        "sample_basis": {
            "pages_classified": len(page_types),
            "urls_discovered": total_discovered,
            "warning": "A capped crawl can prove presence, not absence. Missing pillars are opportunities to validate, not automatic publishing instructions.",
        },
        "quality_guardrail": "Do not mass-produce near-duplicate pages. Programmatic pages should expose unique data, workflows, examples, or functional utility.",
    }
