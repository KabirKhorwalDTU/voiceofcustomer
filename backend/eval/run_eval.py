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


class EvalSettings:
    provider = "gemini"
    model = "gemini-2.5-flash"
    batch_size = 25


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
    bucket_hits = 0
    severity_hits = 0
    for item, review in zip(fixture, reviews):
        tag = by_hash[review.review_hash]
        bucket_hits += int(tag.bucket == item["bucket"])
        severity_hits += int(tag.severity == item["severity"])
    bucket_accuracy = bucket_hits / len(fixture)
    severity_accuracy = severity_hits / len(fixture)
    score = (bucket_accuracy * 0.75) + (severity_accuracy * 0.25)
    print(json.dumps({
        "fixture_count": len(fixture),
        "bucket_accuracy": round(bucket_accuracy, 4),
        "severity_accuracy": round(severity_accuracy, 4),
        "weighted_score": round(score, 4),
        "provider": gateway.provider,
        "model": gateway.model,
        "dev_fallback": gateway._dev_mode,
    }, indent=2))
    return 0 if score >= 0.7 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

