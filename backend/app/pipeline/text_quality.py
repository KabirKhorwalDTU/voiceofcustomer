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
_TRADE_POST_PATTERNS = (
    re.compile(r"(?:^|\s)\[H\].*\[W\]", re.I),
    re.compile(r"\b(?:coupon|voucher|gift card)\s+(?:for sale|available)\b", re.I),
)
_PEER_COMPARISON_PATTERNS = (
    re.compile(r"\b(?:vs\.?|versus)\b", re.I),
    re.compile(r"\b(?:which|what)\s+(?:one|provider|plan|service)\s+(?:is|should)\b", re.I),
    re.compile(r"\b(?:need|looking for)\s+(?:suggestions|recommendations|advice)\b", re.I),
    re.compile(r"\b(?:anyone|somebody)\s+(?:used|tried|know|recommend)\b", re.I),
    re.compile(r"\bidk whether\b", re.I),
)
_EXPERIENCED_FAILURE_PATTERN = re.compile(
    r"\b(?:failed|failure|broken|stuck|down|outage|disconnected|disconnects?|"
    r"dropped|dropping|not working|doesn'?t work|can'?t|cannot|unable|"
    r"no signal|no network|no internet|slow|charged|deducted|refund|"
    r"complaint|issue|problem|poor service)\b",
    re.I,
)
_INFORMATION_QUESTION_PATTERN = re.compile(
    r"\?|^(?:how|what|why|does|do|can|is|are|where|when|which)\b",
    re.I,
)


def is_marketplace_listing(text: str) -> bool:
    compact = text or ""
    return any(pattern.search(compact) for pattern in (*_LISTING_PATTERNS, *_TRADE_POST_PATTERNS))


def is_advice_seeking_without_firsthand_experience(text: str) -> bool:
    compact = text or ""
    advice_request = any(pattern.search(compact) for pattern in _ADVICE_SEEKING_PATTERNS)
    return advice_request and not has_firsthand_experience(compact)


def has_firsthand_experience(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in _FIRSTHAND_EXPERIENCE_PATTERNS)


def is_peer_advice_or_comparison(text: str) -> bool:
    """Flag recommendation threads that do not report an experienced failure."""
    compact = text or ""
    return (
        any(pattern.search(compact) for pattern in _PEER_COMPARISON_PATTERNS)
        and not _EXPERIENCED_FAILURE_PATTERN.search(compact)
    )


def is_information_request_without_experience(text: str) -> bool:
    compact = text or ""
    return bool(
        _INFORMATION_QUESTION_PATTERN.search(compact)
        and not has_firsthand_experience(compact)
        and not _EXPERIENCED_FAILURE_PATTERN.search(compact)
    )


def is_non_experiential_signal(text: str) -> bool:
    """Identify posts that are not evidence of an experienced product or service issue."""
    return (
        is_marketplace_listing(text)
        or is_advice_seeking_without_firsthand_experience(text)
        or is_peer_advice_or_comparison(text)
        or is_information_request_without_experience(text)
    )
