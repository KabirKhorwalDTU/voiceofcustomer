import asyncio
from datetime import date

import pytest

from app.config import AppConfig
from app.pipeline.apify import build_actor_input, redact_error, scrape_sources
from app.config import get_config
from app.pipeline.cleaner import clean_and_dedup, review_hash
from app.pipeline.gateway import LLMGateway
from app.pipeline.gateway import redact_llm_error
from app.pipeline.resolver import resolve_links
from app.pipeline.types import CleanReview, RawReview


class TestSettings:
    provider = "gemini"
    model = "gemini-3.1-flash-lite"
    batch_size = 100
    max_reviews = 50
    per_run_budget_usd = 1


class TestCompany:
    name = "Example Pay"
    brand_keyword = "examplepay"
    play_id = "com.example.pay"
    app_id = "123456789"
    domain = "examplepay.com"
    maps_enabled = False
    maps_location_hint = "India"


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


def test_resolver_prefers_company_slug_for_prefixed_domains():
    resolved = resolve_links(
        "https://play.google.com/store/apps/details?id=com.company.pronto",
        "https://apps.apple.com/in/app/pronto/id6743402816",
        "https://withpronto.com/",
        "Pronto",
    )

    assert resolved.brand_keyword == "pronto"


def test_cleaner_dedups_near_duplicate_reviews():
    raw = [
        RawReview(source="play", text="Payment failed and money debited", date=date.today(), rating=1),
        RawReview(source="play", text="Payment failed and money debited", date=date.today(), rating=1),
        RawReview(source="reddit", text="App is fast and easy", date=date.today(), rating=5),
    ]
    cleaned, ratio = clean_and_dedup(raw, 0.86)
    assert len(cleaned) == 2
    assert ratio > 0


def test_reddit_actor_input_uses_verified_search_schema():
    payload = build_actor_input("reddit", TestCompany(), 100)

    assert payload["searchPosts"] is True
    assert payload["searchComments"] is False
    assert payload["searchTerms"] == ["examplepay"]
    assert payload["searchSort"] == "new"
    assert payload["maxPostsCount"] == 100
    assert payload["maxCommentsPerPost"] == 0
    assert payload["proxy"] == {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]}


def test_gemini_batch_request_shape_matches_docs():
    gateway = LLMGateway(get_config(), TestSettings())
    request = gateway._generate_request("{}", {"key": "batch-0"})

    assert request == {
        "request": {
            "contents": [{"parts": [{"text": "{}"}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        },
        "metadata": {"key": "batch-0"},
    }


def test_gemini_sync_cost_uses_flash_lite_token_pricing():
    gateway = LLMGateway(get_config(), TestSettings())

    gateway._record_token_usage(input_tokens=6_500_000, output_tokens=710_000, total_tokens=7_210_000, path="sync")

    assert gateway.usage.input_tokens == 6_500_000
    assert gateway.usage.output_tokens == 710_000
    assert gateway.usage.cost_usd == 2.69


def test_gemini_batch_cost_uses_half_price_token_pricing():
    gateway = LLMGateway(get_config(), TestSettings())

    gateway._record_token_usage(input_tokens=6_500_000, output_tokens=710_000, total_tokens=7_210_000, path="batch")

    assert gateway.usage.cost_usd == 1.345


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


def test_scraper_does_not_use_dev_samples_when_production_fallback_disabled():
    async def run():
        config = AppConfig(apify_token="", allow_dev_ingestion_fallback=False)
        reviews, completeness, counts, cost = await scrape_sources(TestCompany(), TestSettings(), config)
        assert reviews == []
        assert cost == 0
        assert set(counts.values()) == {0}
        assert completeness["maps"]["status"] == "disabled"
        assert completeness["mouthshut"]["status"] == "disabled"
        assert completeness["reddit"]["status"] == "failed"
        assert "APIFY_TOKEN" in completeness["reddit"]["error"]

    asyncio.run(run())


def test_scraper_cost_only_counts_explicit_paid_source_costs(monkeypatch):
    async def oss_reviews(source, _company, _max_reviews):
        return [
            RawReview(source=source, text=f"{source} review {index}", date=date.today(), rating=5)
            for index in range(5)
        ]

    async def actor_reviews(source, _company, _max_reviews, _config, place_ids=None):
        return [
            RawReview(source=source, text=f"{source} review {index}", date=date.today(), rating=None)
            for index in range(10)
        ]

    async def run():
        monkeypatch.setattr("app.pipeline.apify.run_oss_store_scraper", oss_reviews)
        monkeypatch.setattr("app.pipeline.apify.run_actor", actor_reviews)
        config = AppConfig(apify_token="test-token", allow_dev_ingestion_fallback=False)
        reviews, completeness, counts, cost = await scrape_sources(TestCompany(), TestSettings(), config)

        assert len(reviews) == 20
        assert counts["play"] == 5
        assert counts["appstore"] == 5
        assert counts["reddit"] == 10
        assert completeness["play"]["provider"] == "oss"
        assert completeness["play"]["cost_usd"] == 0
        assert completeness["appstore"]["provider"] == "oss"
        assert completeness["appstore"]["cost_usd"] == 0
        assert completeness["reddit"]["provider"] == "apify"
        assert cost == 0.001

    asyncio.run(run())


def test_apify_errors_redact_tokens():
    error = (
        "Client error for url "
        "'https://api.apify.com/v2/acts/example/run-sync-get-dataset-items?"
        "token=apify_api_secret123&timeout=180'"
    )

    redacted = redact_error(error)

    assert "apify_api_secret123" not in redacted
    assert "token=[redacted]" in redacted


def test_llm_errors_redact_provider_keys():
    error = "Server error for url 'https://generativelanguage.googleapis.com/v1beta/models/x:generateContent?key=AQ.secret123'"

    redacted = redact_llm_error(error)

    assert "AQ.secret123" not in redacted
    assert "key=[redacted]" in redacted


def test_gateway_validation_defaults_null_severity():
    review = CleanReview(
        source="maps",
        review_hash="abc",
        text="Good service",
        date=date.today(),
        rating=5,
        language="en",
    )
    gateway = LLMGateway(get_config(), TestSettings())
    tags = gateway._validate_tags(
        [{"review_hash": "abc", "language": "en", "english_gloss": "Good service", "bucket": "praise", "theme": "other", "severity": None}],
        [review],
        {"complaint": ["other"], "feature_request": ["other"], "praise": ["other"]},
    )

    assert tags[0].severity == 1


def test_gateway_quarantines_theme_discovery_provider_failure():
    async def run():
        review = CleanReview(
            source="maps",
            review_hash="abc",
            text="Payment failed",
            date=date.today(),
            rating=1,
            language="en",
        )
        gateway = LLMGateway(AppConfig(gemini_api_key="test", allow_dev_llm_fallback=False), TestSettings())

        async def fail(_payload):
            raise RuntimeError("provider unavailable")

        gateway._json_call = fail
        themes = await gateway.discover_themes([review])

        assert "payments_or_refunds" in themes["complaint"]
        assert gateway.usage.quarantined_batches == 1

    asyncio.run(run())


def test_gateway_quarantines_classification_provider_failure():
    async def run():
        review = CleanReview(
            source="maps",
            review_hash="abc",
            text="Payment failed",
            date=date.today(),
            rating=1,
            language="en",
        )
        gateway = LLMGateway(AppConfig(gemini_api_key="test", allow_dev_llm_fallback=False), TestSettings())

        async def fail(_payload):
            raise RuntimeError("provider unavailable")

        gateway._json_call = fail
        tags = await gateway.classify_batch([review], {"complaint": ["other"], "feature_request": ["other"], "praise": ["other"]})

        assert tags[0].review_hash == "abc"
        assert tags[0].theme == "other"
        assert gateway.usage.quarantined_batches == 1

    asyncio.run(run())


def test_gateway_requires_provider_key_when_dev_fallback_disabled():
    async def run():
        text = "Payment failed and money debited"
        review = CleanReview(
            source="play",
            review_hash=review_hash("play", text, date.today()),
            text=text,
            date=date.today(),
            rating=1,
            language="en",
        )
        config = AppConfig(gemini_api_key="", allow_dev_llm_fallback=False)
        gateway = LLMGateway(config, TestSettings())
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            await gateway.discover_themes([review])

    asyncio.run(run())
