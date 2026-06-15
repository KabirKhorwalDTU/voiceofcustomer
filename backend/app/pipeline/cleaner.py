import hashlib
import re
from datetime import date
from typing import Iterable, List, Optional, Sequence, Tuple

from datasketch import MinHash, MinHashLSH

from app.pipeline.types import CleanReview, RawReview


HINGLISH_HINTS = {
    "hai",
    "nahi",
    "nahin",
    "kya",
    "kyu",
    "kyun",
    "paise",
    "paisa",
    "kar",
    "karte",
    "mat",
    "bahut",
    "bekar",
    "achha",
    "acha",
}


def normalize_text(text: str) -> str:
    # Postgres text columns reject NUL bytes; scrapers occasionally return them
    # from malformed store payloads, so strip unsafe control characters here.
    safe = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", " ", text or "")
    return re.sub(r"\s+", " ", safe).strip()


def review_hash(source: str, text: str, review_date: Optional[date]) -> str:
    payload = f"{source}|{normalize_text(text).lower()}|{review_date.isoformat() if review_date else ''}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def detect_language(text: str) -> str:
    if re.search(r"[\u0900-\u097F]", text):
        return "hi"
    tokens = set(re.findall(r"[a-zA-Z]+", text.lower()))
    if tokens & HINGLISH_HINTS:
        return "hinglish"
    if re.search(r"[a-zA-Z]", text):
        return "en"
    return "other"


def _shingles(text: str, width: int = 5) -> Sequence[str]:
    words = re.findall(r"\w+", text.lower())
    if len(words) <= width:
        return [" ".join(words)] if words else [text.lower()]
    return [" ".join(words[i : i + width]) for i in range(len(words) - width + 1)]


def _minhash(text: str) -> MinHash:
    mh = MinHash(num_perm=64)
    for shingle in _shingles(text):
        mh.update(shingle.encode("utf-8"))
    return mh


def clean_and_dedup(raw_reviews: Iterable[RawReview], threshold: float) -> Tuple[List[CleanReview], float]:
    cleaned: List[CleanReview] = []
    exact_seen = set()
    lsh = MinHashLSH(threshold=threshold, num_perm=64)
    total = 0
    duplicates = 0

    for raw in raw_reviews:
        total += 1
        text = normalize_text(raw.text)
        if not text:
            duplicates += 1
            continue
        key = review_hash(raw.source, text, raw.date)
        if key in exact_seen:
            duplicates += 1
            continue
        mh = _minhash(text)
        near = lsh.query(mh)
        if near:
            duplicates += 1
            continue
        lsh.insert(key, mh)
        exact_seen.add(key)
        cleaned.append(
            CleanReview(
                source=raw.source,
                review_hash=key,
                text=text,
                date=raw.date,
                rating=raw.rating,
                language=detect_language(text),
            )
        )

    ratio = duplicates / total if total else 0
    return cleaned, ratio
