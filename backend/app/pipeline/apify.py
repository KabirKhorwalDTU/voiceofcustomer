import asyncio
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

import httpx

from app.config import AppConfig
from app.pipeline.types import RawReview, SOURCES


ACTORS: Dict[str, Dict[str, str]] = {
    "play": {"id": "neatrat/google-play-store-reviews-scraper", "version": "resolve-with-apify-token"},
    "appstore": {"id": "thewolves/appstore-reviews-scraper", "version": "resolve-with-apify-token"},
    "reddit": {"id": "trudax/reddit-scraper", "version": "resolve-with-apify-token"},
    "maps": {"id": "compass/google-maps-reviews-scraper", "version": "resolve-with-apify-token"},
    "mouthshut": {"id": "getdataforme/mouthshut-reviews-scraper", "version": "resolve-with-apify-token"},
}

APIFY_RESULT_COST_PER_1000 = 0.10


class BudgetExceeded(Exception):
    pass


def source_cap(source: str, max_reviews: int) -> int:
    if source == "maps":
        return min(max_reviews, 100)
    if source in {"reddit", "mouthshut"}:
        return min(max_reviews, 500)
    return max_reviews


def estimate_cost(count: int) -> float:
    return round((count / 1000) * APIFY_RESULT_COST_PER_1000, 4)


def _parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date):
        return value
    text = str(value)
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(text[: len(fmt.replace("%f", "000000"))], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _field(item: Dict[str, Any], names: Iterable[str]) -> Any:
    for name in names:
        if name in item and item[name] not in (None, ""):
            return item[name]
    return None


def normalize_item(source: str, item: Dict[str, Any]) -> Optional[RawReview]:
    text = _field(item, ["text", "review", "content", "body", "comment", "title"])
    if not text:
        return None
    rating = _field(item, ["rating", "score", "stars"])
    try:
        rating_int = int(float(rating)) if rating is not None else None
    except (TypeError, ValueError):
        rating_int = None
    return RawReview(
        source=source,
        text=str(text),
        date=_parse_date(_field(item, ["date", "publishedAt", "createdAt", "at", "timestamp"])),
        rating=rating_int,
        external_id=str(_field(item, ["id", "reviewId", "url", "permalink"]) or ""),
    )


def build_actor_input(source: str, company: Any, max_reviews: int) -> Dict[str, Any]:
    cap = source_cap(source, max_reviews)
    if source == "play":
        return {"appId": company.play_id, "maxReviews": cap, "sort": "newest"}
    if source == "appstore":
        return {"appId": company.app_id, "country": "in", "maxItems": cap, "sort": "mostRecent"}
    if source == "reddit":
        return {"searches": [company.brand_keyword], "maxItems": cap, "sort": "new"}
    if source == "maps":
        return {"searchStringsArray": [company.brand_keyword], "maxReviews": cap, "language": "en"}
    if source == "mouthshut":
        return {"query": company.brand_keyword, "maxItems": cap}
    return {}


async def run_actor(source: str, company: Any, max_reviews: int, config: AppConfig) -> List[RawReview]:
    actor_id = ACTORS[source]["id"].replace("/", "~")
    run_url = f"https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items"
    params = {"token": config.apify_token, "timeout": 180, "memory": 1024}
    payload = build_actor_input(source, company, max_reviews)
    async with httpx.AsyncClient(timeout=240) as client:
        response = await client.post(run_url, params=params, json=payload)
        response.raise_for_status()
        items = response.json()
    normalized = [review for item in items if (review := normalize_item(source, item))]
    return normalized[: source_cap(source, max_reviews)]


def dev_reviews(company: Any, max_reviews: int) -> List[RawReview]:
    today = date.today()
    base = company.brand_keyword or company.name
    samples = [
        ("play", 1, f"{base} app login nahi ho raha, payment stuck hai and support is slow."),
        ("play", 5, f"{base} UPI flow is quick and clean, loved the new dashboard."),
        ("appstore", 2, f"Refund status unclear. Paise debit ho gaye but confirmation nahi mila."),
        ("appstore", 4, f"Good experience overall, but I want better spend analytics."),
        ("reddit", None, f"Anyone else seeing {base} KYC fail after uploading Aadhaar twice?"),
        ("reddit", None, f"{base} fees are transparent compared with my older wallet."),
        ("maps", 3, f"Branch staff helped eventually, but waiting time was too much."),
        ("mouthshut", 1, f"Customer care ne ticket close kar diya without solving issue."),
        ("mouthshut", 5, f"Bahut easy app hai, settlement fast mila."),
    ]
    reviews: List[RawReview] = []
    for idx, (source, rating, text) in enumerate(samples):
        if len(reviews) >= min(max_reviews, len(samples)):
            break
        reviews.append(RawReview(source=source, rating=rating, text=text, date=today - timedelta(days=idx * 5)))
    return reviews


async def scrape_sources(company: Any, settings: Any, config: AppConfig, current_cost: float = 0) -> Tuple[List[RawReview], Dict[str, Any], Dict[str, int], float]:
    if not config.apify_token:
        reviews = dev_reviews(company, min(settings.max_reviews, 50))
        counts = {source: sum(1 for review in reviews if review.source == source) for source in SOURCES}
        completeness = {
            source: {"status": "ok", "mode": "dev_sample", "attempts": 0, "count": counts[source]}
            for source in SOURCES
        }
        return reviews, completeness, counts, current_cost

    all_reviews: List[RawReview] = []
    completeness: Dict[str, Any] = {}
    counts: Dict[str, int] = {}
    cost = current_cost

    async def scrape_one(source: str) -> Tuple[str, List[RawReview], Dict[str, Any]]:
        last_error = ""
        for attempt in range(1, 4):
            try:
                items = await run_actor(source, company, settings.max_reviews, config)
                return source, items, {"status": "ok", "attempts": attempt, "actor": ACTORS[source], "count": len(items)}
            except Exception as exc:
                last_error = str(exc)
                await asyncio.sleep(attempt * 2)
        return source, [], {"status": "failed", "attempts": 3, "actor": ACTORS[source], "error": last_error, "count": 0}

    results = await asyncio.gather(*(scrape_one(source) for source in SOURCES))
    for source, reviews, status in results:
        projected = cost + estimate_cost(len(reviews))
        if projected > float(settings.per_run_budget_usd):
            completeness[source] = {**status, "status": "aborted_budget", "count": 0}
            raise BudgetExceeded(f"Budget exceeded while adding {source}: projected ${projected:.4f}")
        cost = projected
        all_reviews.extend(reviews)
        completeness[source] = status
        counts[source] = len(reviews)

    return all_reviews, completeness, counts, cost
