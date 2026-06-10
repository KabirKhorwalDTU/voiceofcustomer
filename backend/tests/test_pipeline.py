import asyncio
from datetime import date

from app.config import get_config
from app.pipeline.cleaner import clean_and_dedup, review_hash
from app.pipeline.gateway import LLMGateway
from app.pipeline.resolver import resolve_links
from app.pipeline.types import CleanReview, RawReview


class TestSettings:
    provider = "gemini"
    model = "gemini-2.5-flash"
    batch_size = 25


def test_resolver_extracts_store_ids_and_brand_keyword():
    resolved = resolve_links(
        "https://play.google.com/store/apps/details?id=com.example.pay",
        "https://apps.apple.com/in/app/example/id123456789",
        "https://www.examplepay.com",
        "Example Pay",
    )
    assert resolved.play_id == "com.example.pay"
    assert resolved.app_id == "123456789"
    assert resolved.domain == "examplepay.com"
    assert resolved.brand_keyword == "examplepay"


def test_cleaner_dedups_near_duplicate_reviews():
    raw = [
        RawReview(source="play", text="Payment failed and money debited", date=date.today(), rating=1),
        RawReview(source="play", text="Payment failed and money debited", date=date.today(), rating=1),
        RawReview(source="reddit", text="App is fast and easy", date=date.today(), rating=5),
    ]
    cleaned, ratio = clean_and_dedup(raw, 0.86)
    assert len(cleaned) == 2
    assert ratio > 0


def test_gateway_dev_classifier_handles_hinglish():
    async def run():
        text = "Paise debit ho gaye but payment nahi mila"
        review = CleanReview(
            source="play",
            review_hash=review_hash("play", text, date.today()),
            text=text,
            date=date.today(),
            rating=1,
            language="hinglish",
        )
        gateway = LLMGateway(get_config(), TestSettings())
        theme_set = await gateway.discover_themes([review])
        tags, usage = await gateway.classify_all([review], theme_set)
        assert tags[0].bucket == "complaint"
        assert tags[0].severity == 3
        assert tags[0].theme == "payments_or_refunds"
        assert usage.total_batches == 1

    asyncio.run(run())
