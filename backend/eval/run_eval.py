import asyncio
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_config
from app.pipeline.cleaner import review_hash
from app.pipeline.gateway import LLMGateway
from app.pipeline.types import CleanReview


TOPIC_KEYWORDS = {
    "payments_or_refunds": {"payment", "refund", "debit", "cashback", "settlement", "money", "paise", "amount", "autopay"},
    "login_or_kyc": {"login", "otp", "kyc", "aadhaar", "account", "locked", "verification"},
    "support_quality": {"support", "care", "ticket", "call", "chat", "agent", "response", "rude"},
    "app_reliability": {"app", "crash", "hang", "freeze", "slow", "bug", "error", "screen", "update"},
    "pricing_or_fees": {"price", "pricing", "fee", "fees", "charge", "charges", "bill", "cost", "expensive"},
    "delivery_or_service_fulfillment": {"delivery", "service", "booking", "slot", "late", "delay", "arrived", "reschedule"},
    "quality_or_professionalism": {"quality", "professional", "staff", "cleaner", "maid", "wrong", "incomplete", "rotten", "replacement"},
}


class EvalSettings:
    provider = "gemini"
    model = "gemini-3.1-flash-lite"
    batch_size = 100


def canonical_topic(label: str) -> str:
    normalized = (label or "other").lower()
    if normalized == "other":
        return "other"
    if normalized in TOPIC_KEYWORDS:
        return normalized
    tokens = set(normalized.replace("-", "_").split("_"))
    tokens |= {token[:-1] for token in tokens if token.endswith("s") and len(token) > 3}
    best_topic = "other"
    best_hits = 0
    for topic, keywords in TOPIC_KEYWORDS.items():
        hits = len(tokens & keywords)
        if hits > best_hits:
            best_topic = topic
            best_hits = hits
    return best_topic


async def main() -> int:
    fixture_path = Path(__file__).with_name("hinglish_fixture.json")
    fixture = json.loads(fixture_path.read_text())
    reviews = [
        CleanReview(
            source="play",
            review_hash=review_hash("play", item["text"], date.today()),
            text=item["text"],
            date=date.today(),
            rating=item.get("rating"),
            language="hinglish",
        )
        for item in fixture
    ]
    gateway = LLMGateway(get_config(), EvalSettings())
    theme_set = await gateway.discover_themes(reviews)
    tags, _ = await gateway.classify_all(reviews, theme_set)
    by_hash = {tag.review_hash: tag for tag in tags}
    l1_hits = 0
    topic_totals = {}
    topic_hits = {}
    other_count = 0
    l2_count = 0
    examples = []
    for item, review in zip(fixture, reviews):
        tag = by_hash[review.review_hash]
        expected = item["expected_l1"]
        predicted = canonical_topic(tag.theme)
        hit = int(predicted == expected)
        l1_hits += hit
        topic_totals[expected] = topic_totals.get(expected, 0) + 1
        topic_hits[expected] = topic_hits.get(expected, 0) + hit
        other_count += int(tag.theme == "other")
        l2_count += int(bool(tag.l2_theme) and tag.l2_theme != "other")
        if len(examples) < 8:
            examples.append({
                "text": item["text"],
                "expected_l1": expected,
                "predicted_l1": tag.theme,
                "canonical_predicted_l1": predicted,
                "predicted_l2": tag.l2_theme,
            })
    l1_accuracy = l1_hits / len(fixture)
    other_rate = other_count / len(fixture)
    l2_assignment_rate = l2_count / len(fixture)
    print(json.dumps({
        "fixture_count": len(fixture),
        "canonical_l1_accuracy": round(l1_accuracy, 4),
        "other_rate": round(other_rate, 4),
        "l2_assignment_rate": round(l2_assignment_rate, 4),
        "per_topic_accuracy": {
            topic: round(topic_hits.get(topic, 0) / total, 4)
            for topic, total in sorted(topic_totals.items())
        },
        "theme_set": theme_set,
        "examples": examples,
        "provider": gateway.provider,
        "model": gateway.model,
        "dev_fallback": gateway._dev_mode,
    }, indent=2))
    return 0 if l1_accuracy >= 0.7 and other_rate <= 0.2 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
