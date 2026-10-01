import re


_ADVICE_SEEKING_PATTERNS = (
    re.compile(r"\bplanning to (?:visit|travel|go|use)\b", re.I),
    re.compile(r"\blooking for advice\b", re.I),
    re.compile(r"\banyone (?:who )?(?:has )?visited\b", re.I),
    re.compile(r"\banyone can help\b", re.I),
    re.compile(r"\bcan we (?:make|place) calls\b", re.I),
    re.compile(r"\bshould i\b", re.I),
)
_FIRSTHAND_EXPERIENCE_PATTERNS = (
    re.compile(r"\b(?:i|we) (?:have |had |was |were |been |got |tried |used |visited |faced )", re.I),
    re.compile(r"\b(?:i|we) am (?:facing|experiencing|using|getting|having)\b", re.I),
    re.compile(r"\bmy (?:service|network|connection|account|order|payment|bill|device|app)\b", re.I),
)
_LISTING_PATTERNS = (
    re.compile(r"\b(?:for sale|want to sell|looking to sell|selling my|selling this)\b", re.I),
)


def is_marketplace_listing(text: str) -> bool:
    compact = text or ""
    return any(pattern.search(compact) for pattern in _LISTING_PATTERNS)


def is_advice_seeking_without_firsthand_experience(text: str) -> bool:
    compact = text or ""
    advice_request = any(pattern.search(compact) for pattern in _ADVICE_SEEKING_PATTERNS)
    return advice_request and not has_firsthand_experience(compact)


def has_firsthand_experience(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in _FIRSTHAND_EXPERIENCE_PATTERNS)


def is_non_experiential_signal(text: str) -> bool:
    """Identify posts that are not evidence of an experienced product or service issue."""
    return is_marketplace_listing(text) or is_advice_seeking_without_firsthand_experience(text)
