"""Source planning rules for the low-friction business onboarding flow."""

from __future__ import annotations

from typing import Dict, Iterable, List


SOURCE_ORDER = ("play", "appstore", "maps", "instagram", "twitter", "reddit", "mouthshut")
SUPPORTED_SOURCES = frozenset(SOURCE_ORDER)

BUSINESS_TYPES: Dict[str, Dict[str, object]] = {
    "app": {
        "label": "App or digital service",
        "recommended": ("play", "appstore"),
    },
    "local_business": {
        "label": "Local shop or service",
        "recommended": ("maps", "instagram"),
    },
    "creator_brand": {
        "label": "Creator or personal brand",
        "recommended": ("instagram", "twitter"),
    },
    "online_business": {
        "label": "Online business or brand",
        "recommended": ("instagram", "twitter"),
    },
    "other": {
        "label": "Something else",
        "recommended": ("maps", "instagram"),
    },
}

SOURCE_CATALOG: Dict[str, Dict[str, object]] = {
    "play": {
        "label": "Google Play",
        "short_description": "Recent 1-3 star app reviews",
        "identity_field": "",
        "cap": 5000,
    },
    "appstore": {
        "label": "App Store",
        "short_description": "Recent 1-3 star iPhone app reviews",
        "identity_field": "",
        "cap": 500,
    },
    "maps": {
        "label": "Google Maps",
        "short_description": "Lowest-rated reviews from matched India places",
        "identity_field": "maps_url",
        "cap": 100,
    },
    "instagram": {
        "label": "Instagram",
        "short_description": "Brand post comments and public mentions",
        "identity_field": "instagram_url",
        "cap": 100,
    },
    "twitter": {
        "label": "X / Twitter",
        "short_description": "Brand posts, replies, and public mentions",
        "identity_field": "twitter_url",
        "cap": 100,
    },
    "reddit": {
        "label": "Reddit",
        "short_description": "Recent public brand discussions",
        "identity_field": "",
        "cap": 100,
    },
    "mouthshut": {
        "label": "MouthShut",
        "short_description": "Public consumer reviews in India",
        "identity_field": "mouthshut_url",
        "cap": 100,
    },
}


def normalize_business_type(value: str) -> str:
    return value if value in BUSINESS_TYPES else "other"


def normalize_sources(values: Iterable[str] | None, business_type: str) -> List[str]:
    requested = {value for value in (values or []) if value in SUPPORTED_SOURCES}
    if not requested:
        requested = set(recommended_sources(business_type))
    return [source for source in SOURCE_ORDER if source in requested]


def recommended_sources(business_type: str) -> List[str]:
    normalized = normalize_business_type(business_type)
    return list(BUSINESS_TYPES[normalized]["recommended"])


def source_catalog() -> List[Dict[str, object]]:
    return [{"id": source, **SOURCE_CATALOG[source]} for source in SOURCE_ORDER]


def selected_sources_for_company(company: object) -> List[str]:
    configured = getattr(company, "selected_sources", None)
    if isinstance(configured, list) and configured:
        return normalize_sources(configured, getattr(company, "business_type", "other"))

    # Legacy companies predate enabled_sources. Retain their old map/Reddit choice
    # and give app businesses the original free store sources.
    sources = ["play", "appstore"]
    if getattr(company, "maps_enabled", False):
        sources.append("maps")
    if getattr(company, "reddit_enabled", False):
        sources.append("reddit")
    return sources
