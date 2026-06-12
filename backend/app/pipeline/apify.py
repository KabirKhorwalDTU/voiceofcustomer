import asyncio
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

import httpx

from app.config import AppConfig
from app.pipeline.types import RawReview, SOURCES


ACTORS: Dict[str, Dict[str, str]] = {
    "play": {"id": "neatrat/google-play-store-reviews-scraper", "version": "resolve-with-apify-token"},
    "appstore": {"id": "thewolves/appstore-reviews-scraper", "version": "resolve-with-apify-token"},
    "reddit": {"id": "harshmaur/reddit-scraper", "version": "resolve-with-apify-token"},
    "maps": {"id": "compass/google-maps-reviews-scraper", "version": "resolve-with-apify-token"},
    "mouthshut": {"id": "getdataforme/mouthshut-reviews-scraper", "version": "disabled-by-default"},
}

ENABLE_PAID_STORE_FALLBACK = False
APIFY_EVENT_PRICING: Dict[str, Dict[str, float]] = {
    "play": {"actor_start": 0.0, "per_result": 0.00015},
    "appstore": {"actor_start": 0.0, "per_result": 0.00010},
    "reddit": {"actor_start": 0.02, "per_result": 0.00200},
    "maps": {"actor_start": 0.00005, "per_result": 0.00060},
    "mouthshut": {"actor_start": 0.0, "per_result": 0.0},
}
SECRET_PATTERNS = (
    re.compile(r"token=([^&\\s'\\\"]+)"),
    re.compile(r"key=([^&\\s'\\\"]+)"),
    re.compile(r"apify_api_[A-Za-z0-9_-]+"),
    re.compile(r"AIza[A-Za-z0-9_-]+"),
)


class BudgetExceeded(Exception):
    pass


def source_cap(source: str, max_reviews: int) -> int:
    if source == "maps":
        return min(max_reviews, 1000)
    if source == "reddit":
        return min(max_reviews, 100)
    if source == "mouthshut":
        return 0
    return max_reviews


def estimate_cost(source: str, count: int) -> float:
    pricing = APIFY_EVENT_PRICING.get(source, {"actor_start": 0.0, "per_result": 0.00010})
    if count <= 0:
        return 0
    return round(pricing["actor_start"] + (count * pricing["per_result"]), 4)


def redact_error(value: Union[Exception, str]) -> str:
    text = str(value)
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(_redact_match, text)
    return text


def format_response_error(response: httpx.Response) -> str:
    try:
        body: Any = response.json()
    except ValueError:
        body = response.text
    formatted = json.dumps(body, ensure_ascii=False) if not isinstance(body, str) else body
    return redact_error(f"HTTP {response.status_code} for {response.request.url}: {formatted}")


def _redact_match(match: re.Match) -> str:
    value = match.group(0)
    if value.startswith("token="):
        return "token=[redacted]"
    if value.startswith("key="):
        return "key=[redacted]"
    return "[redacted]"


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
    if source == "reddit":
        title = str(_field(item, ["title"]) or "").strip()
        body = str(_field(item, ["body", "content", "text"]) or "").strip()
        text = "\n".join(part for part in [title, body] if part)
    else:
        text = _field(item, ["text", "review", "content", "body", "comment", "title"])
    if not text:
        return None
    if source == "reddit":
        rating_int = None
    else:
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


def normalize_oss_item(source: str, item: Dict[str, Any]) -> Optional[RawReview]:
    text = item.get("text")
    if not text:
        return None
    rating = item.get("rating")
    try:
        rating_int = int(float(rating)) if rating is not None else None
    except (TypeError, ValueError):
        rating_int = None
    return RawReview(
        source=source,
        text=str(text),
        date=_parse_date(item.get("date")),
        rating=rating_int,
        external_id=str(item.get("external_id") or ""),
    )


def build_actor_input(source: str, company: Any, max_reviews: int, place_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    cap = source_cap(source, max_reviews)
    if source == "play":
        return {"appIdOrUrl": company.play_id, "sortBy": "recent", "maxReviews": cap}
    if source == "appstore":
        return {"appId": company.app_id, "country": "in", "maxItems": cap, "sort": "mostRecent"}
    if source == "reddit":
        return {
            "searchPosts": True,
            "searchComments": False,
            "searchCommunities": False,
            "searchTerms": [company.brand_keyword],
            "searchSort": "new",
            "searchTime": "all",
            "maxPostsCount": cap,
            "maxCommentsPerPost": 0,
            "crawlCommentsPerPost": False,
            "includeNSFW": False,
            "proxy": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]},
        }
    if source == "maps":
        if place_ids:
            return {"placeIds": place_ids, "maxReviews": cap, "language": "en"}
        return {"searchStringsArray": [company.brand_keyword], "maxReviews": cap, "language": "en"}
    if source == "mouthshut":
        return {"query": company.brand_keyword, "maxItems": cap}
    return {}


async def run_actor(source: str, company: Any, max_reviews: int, config: AppConfig, place_ids: Optional[List[str]] = None) -> List[RawReview]:
    actor_id = ACTORS[source]["id"].replace("/", "~")
    run_url = f"https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items"
    params = {"timeout": 180, "memory": 512 if source == "reddit" else 1024}
    headers = {"Authorization": f"Bearer {config.apify_token}"}
    payload = build_actor_input(source, company, max_reviews, place_ids)
    async with httpx.AsyncClient(timeout=240) as client:
        response = await client.post(run_url, params=params, headers=headers, json=payload)
        if response.is_error:
            raise RuntimeError(format_response_error(response))
        items = response.json()
    normalized = [review for item in items if (review := normalize_item(source, item))]
    return normalized[: source_cap(source, max_reviews)]


async def run_oss_store_scraper(source: str, company: Any, max_reviews: int) -> List[RawReview]:
    if source == "play" and not company.play_id:
        raise ValueError("missing Play Store app id")
    if source == "appstore" and not company.app_id:
        raise ValueError("missing App Store app id")
    script = Path(__file__).resolve().parents[2] / "scrapers" / "app_reviews.js"
    payload = {
        "source": source,
        "app_id": company.play_id if source == "play" else company.app_id,
        "max_reviews": source_cap(source, max_reviews),
        "country": "in",
        "langs": ["hi", "en"],
        "throttle": 10,
    }
    proc = await asyncio.create_subprocess_exec(
        "node",
        str(script),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(json.dumps(payload).encode()), timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(stderr.decode("utf-8", errors="replace")[:2000] or "OSS scraper failed")
    items = json.loads(stdout.decode("utf-8"))
    normalized = [review for item in items if (review := normalize_oss_item(source, item))]
    return normalized[: source_cap(source, max_reviews)]


def place_matches_company(place: Dict[str, Any], company: Any) -> bool:
    domain = (company.domain or "").lower().replace("www.", "")
    name = str((place.get("displayName") or {}).get("text") or "").lower()
    keyword = str(company.brand_keyword or company.name or "").lower()
    normalized_name = re.sub(r"[^a-z0-9]+", "", name)
    normalized_keyword = re.sub(r"[^a-z0-9]+", "", keyword)
    if normalized_keyword and normalized_name == normalized_keyword:
        return True
    if normalized_keyword and normalized_keyword in normalized_name:
        return True
    if domain:
        domain_token = domain.split(".")[0]
        normalized_domain = re.sub(r"[^a-z0-9]+", "", domain_token)
        if normalized_domain and normalized_name == normalized_domain:
            return True
        if normalized_domain and normalized_domain in normalized_name:
            return True
    return False


async def discover_places(company: Any, config: AppConfig) -> Tuple[List[str], List[Dict[str, Any]], List[str]]:
    if not config.google_maps_api_key:
        raise RuntimeError("GOOGLE_MAPS_API_KEY is not configured.")
    location_hint = company.maps_location_hint or "India"
    domain_token = (company.domain or "").lower().replace("www.", "").split(".")[0]
    query_brands = [value for value in [domain_token, company.brand_keyword] if value]
    query_brands = list(dict.fromkeys(query_brands))
    queries = [f"{brand} {location_hint}" for brand in query_brands]
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": config.google_maps_api_key,
        "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.rating,places.userRatingCount",
    }
    all_places: List[Dict[str, Any]] = []
    matched_places: List[Dict[str, Any]] = []
    seen_place_ids: set[str] = set()
    attempted_queries: List[str] = []
    async with httpx.AsyncClient(timeout=30) as client:
        for query in queries:
            attempted_queries.append(query)
            response = await client.post("https://places.googleapis.com/v1/places:searchText", headers=headers, json={"textQuery": query})
            if response.is_error:
                raise RuntimeError(format_response_error(response))
            data = response.json()
            places = data.get("places") or []
            all_places.extend(places)
            matched = [place for place in places if place_matches_company(place, company)]
            if matched:
                for place in matched:
                    place_id = place.get("id")
                    if place_id and place_id not in seen_place_ids:
                        seen_place_ids.add(place_id)
                        matched_places.append(place)
    return [place["id"] for place in matched_places if place.get("id")], matched_places or all_places, attempted_queries


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
    ]
    reviews: List[RawReview] = []
    for idx, (source, rating, text) in enumerate(samples):
        if len(reviews) >= min(max_reviews, len(samples)):
            break
        reviews.append(RawReview(source=source, rating=rating, text=text, date=today - timedelta(days=idx * 5)))
    return reviews


async def scrape_sources(company: Any, settings: Any, config: AppConfig, current_cost: float = 0) -> Tuple[List[RawReview], Dict[str, Any], Dict[str, int], float]:
    if not config.apify_token and config.allow_dev_ingestion_fallback:
        reviews = dev_reviews(company, min(settings.max_reviews, 50))
        counts = {source: sum(1 for review in reviews if review.source == source) for source in SOURCES}
        completeness = {source: {"status": "ok", "mode": "dev_sample", "attempts": 0, "count": counts[source]} for source in SOURCES}
        return reviews, completeness, counts, current_cost

    all_reviews: List[RawReview] = []
    completeness: Dict[str, Any] = {}
    counts: Dict[str, int] = {}
    cost = current_cost

    async def scrape_store_with_fallback(source: str) -> Tuple[str, List[RawReview], Dict[str, Any]]:
        attempt_details: List[Dict[str, Any]] = []
        for attempt in range(1, 4):
            try:
                items = await run_oss_store_scraper(source, company, settings.max_reviews)
                attempt_details.append({"attempt": attempt, "status": "ok", "count": len(items), "provider": "oss"})
                return source, items, {
                    "status": "ok",
                    "provider": "oss",
                    "library": "facundoolano/google-play-scraper" if source == "play" else "facundoolano/app-store-scraper",
                    "attempts": attempt,
                    "count": len(items),
                    "cost_usd": 0,
                    "attempt_details": attempt_details,
                }
            except Exception as exc:
                attempt_details.append({"attempt": attempt, "status": "failed", "provider": "oss", "error": redact_error(exc)})
                await asyncio.sleep(attempt * 2)

        if not ENABLE_PAID_STORE_FALLBACK:
            return source, [], {
                "status": "failed",
                "provider": "oss",
                "attempts": 3,
                "count": 0,
                "cost_usd": 0,
                "attempt_details": attempt_details,
                "error": "OSS scraper failed. Paid Apify store fallback is disabled for cost control.",
            }
        if not config.apify_token:
            return source, [], {"status": "failed", "provider": "oss", "attempts": 3, "count": 0, "cost_usd": 0, "attempt_details": attempt_details, "error": "OSS scraper failed and APIFY_TOKEN is not configured."}

        last_error = ""
        for attempt in range(1, 4):
            try:
                items = await run_actor(source, company, settings.max_reviews, config)
                cost_usd = estimate_cost(source, len(items))
                attempt_details.append({"attempt": attempt, "status": "ok", "provider": "apify", "count": len(items), "cost_usd": cost_usd})
                return source, items, {"status": "ok", "provider": "apify", "actor": ACTORS[source], "attempts": attempt, "count": len(items), "cost_usd": cost_usd, "attempt_details": attempt_details}
            except Exception as exc:
                last_error = redact_error(exc)
                attempt_details.append({"attempt": attempt, "status": "failed", "provider": "apify", "error": last_error})
                await asyncio.sleep(attempt * 2)
        return source, [], {"status": "failed", "provider": "apify", "actor": ACTORS[source], "attempts": 3, "count": 0, "cost_usd": 0, "attempt_details": attempt_details, "error": last_error}

    async def scrape_apify_source(source: str) -> Tuple[str, List[RawReview], Dict[str, Any]]:
        if source == "mouthshut":
            return source, [], {"status": "disabled", "provider": "apify", "actor": ACTORS[source], "attempts": 0, "count": 0, "cost_usd": 0, "reason": "disabled_by_default"}
        if source == "maps" and not company.maps_enabled:
            return source, [], {"status": "disabled", "provider": "apify", "actor": ACTORS[source], "attempts": 0, "count": 0, "cost_usd": 0, "reason": "maps_opt_in_false"}
        if not config.apify_token:
            return source, [], {"status": "failed", "provider": "apify", "actor": ACTORS[source], "attempts": 0, "count": 0, "cost_usd": 0, "error": "APIFY_TOKEN is not configured."}

        place_ids: Optional[List[str]] = None
        places: List[Dict[str, Any]] = []
        place_queries: List[str] = []
        if source == "maps":
            try:
                place_ids, places, place_queries = await discover_places(company, config)
            except Exception as exc:
                return source, [], {"status": "failed", "provider": "places_api", "actor": ACTORS[source], "attempts": 0, "count": 0, "cost_usd": 0, "error": redact_error(exc)}
            if not place_ids:
                return source, [], {"status": "failed", "provider": "places_api", "actor": ACTORS[source], "attempts": 0, "count": 0, "cost_usd": 0, "error": "No matching Places API place_ids found.", "places": places, "placeQueries": place_queries}

        last_error = ""
        attempt_details: List[Dict[str, Any]] = []
        for attempt in range(1, 4):
            try:
                items = await run_actor(source, company, settings.max_reviews, config, place_ids=place_ids)
                cost_usd = estimate_cost(source, len(items))
                attempt_details.append({"attempt": attempt, "status": "ok", "provider": "apify", "count": len(items), "cost_usd": cost_usd})
                status = {"status": "ok", "provider": "apify", "actor": ACTORS[source], "attempts": attempt, "count": len(items), "cost_usd": cost_usd, "attempt_details": attempt_details, "places": places, "placeQueries": place_queries}
                if source == "reddit":
                    status["searchTerms"] = [company.brand_keyword]
                return source, items, status
            except Exception as exc:
                last_error = redact_error(exc)
                attempt_details.append({"attempt": attempt, "status": "failed", "provider": "apify", "error": last_error})
                await asyncio.sleep(attempt * 2)
        status = {"status": "failed", "provider": "apify", "actor": ACTORS[source], "attempts": 3, "count": 0, "cost_usd": 0, "attempt_details": attempt_details, "error": last_error, "places": places, "placeQueries": place_queries}
        if source == "reddit":
            status["searchTerms"] = [company.brand_keyword]
        return source, [], status

    results = await asyncio.gather(
        scrape_store_with_fallback("play"),
        scrape_store_with_fallback("appstore"),
        scrape_apify_source("reddit"),
        scrape_apify_source("maps"),
        scrape_apify_source("mouthshut"),
    )
    for source, reviews, status in results:
        projected = cost + float(status.get("cost_usd") or 0)
        if projected > float(settings.per_run_budget_usd):
            completeness[source] = {**status, "status": "aborted_budget", "count": 0}
            raise BudgetExceeded(f"Budget exceeded while adding {source}: projected ${projected:.4f}")
        cost = projected
        all_reviews.extend(reviews)
        completeness[source] = status
        counts[source] = len(reviews)

    return all_reviews, completeness, counts, cost
