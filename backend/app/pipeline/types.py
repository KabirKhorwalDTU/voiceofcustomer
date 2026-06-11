from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional


SOURCES = ("play", "appstore", "reddit", "maps", "mouthshut")
DEFAULT_SOURCES = ("play", "appstore", "reddit", "maps")
BUCKETS = ("complaint", "feature_request", "praise")


@dataclass
class RawReview:
    source: str
    text: str
    date: Optional[date] = None
    rating: Optional[int] = None
    external_id: str = ""


@dataclass
class CleanReview:
    source: str
    review_hash: str
    text: str
    date: Optional[date]
    rating: Optional[int]
    language: str


@dataclass
class Tag:
    review_hash: str
    language: str
    english_gloss: str
    bucket: str
    theme: str
    severity: int


ThemeSet = Dict[str, List[str]]
