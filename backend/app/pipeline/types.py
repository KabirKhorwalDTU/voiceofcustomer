from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional


SOURCES = ("play", "appstore", "maps", "instagram", "twitter", "reddit", "mouthshut")
DEFAULT_SOURCES = ("play", "appstore")
MAX_L1_THEMES = 20
MAX_L2_THEMES = 10


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
    theme: str
    l2_theme: Optional[str] = None


ThemeSet = Dict[str, List[str]]
