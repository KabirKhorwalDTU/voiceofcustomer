from datetime import date
import json

from app.models import Company, Review, Run, Theme
from app.pipeline.synth import build_deck_spec, export_reviews, humanize_theme


def sample_objects():
    company = Company(
        id="company-1",
        name="Example Pay",
        play_id="com.example.pay",
        app_id="123456789",
        domain="examplepay.com",
        brand_keyword="examplepay",
    )
    run = Run(
        id="run-1",
        company_id=company.id,
        status="done",
        source_counts={"play": 1},
        completeness={"play": {"status": "ok", "count": 1}},
        cost_estimate=0.01,
        budget_cap=1,
        dedup_ratio=0,
        quarantine_rate=0,
    )
    review = Review(
        id="review-1",
        run_id=run.id,
        company_id=company.id,
        review_hash="hash-1",
        source="play",
        date=date(2026, 6, 1),
        rating=1,
        text="Paise debit ho gaye but payment nahi mila",
        language="hinglish",
        english_gloss="Money was debited but payment was not received",
        bucket="complaint",
        theme="payments_or_refunds",
        l2_theme="refund_not_processed",
        severity=3,
        representative_flag=True,
    )
    theme = Theme(
        id="theme-1",
        run_id=run.id,
        company_id=company.id,
        bucket="complaint",
        theme="payments_or_refunds",
        count=1,
        normalized_frequency=1,
        avg_severity=3,
        theme_score=2.7,
        rank=1,
        top_quotes=[
            {
                "text": review.text,
                "english_gloss": review.english_gloss,
                "source": review.source,
                "severity": review.severity,
                "date": review.date.isoformat(),
            }
        ],
        l2_subthemes=[
            {
                "label": "refund_not_processed",
                "display_label": "Refunds: not processed.",
                "count": 1,
                "score": 1,
                "top_quotes": [{"text": review.text, "source": review.source, "rating": review.rating}],
            }
        ],
    )
    return company, run, [review], [theme]


def test_tagged_reviews_json_matches_contract_a_keys():
    _, _, reviews, _ = sample_objects()
    body, media_type, filename = export_reviews(reviews, "json")
    payload = json.loads(body)
    assert media_type == "application/json"
    assert filename == "tagged_reviews.json"
    assert set(payload[0].keys()) == {
        "review_hash",
        "source",
        "date",
        "rating",
        "text",
        "language",
        "english_gloss",
        "bucket",
        "theme",
        "l2_theme",
        "severity",
        "representative_flag",
    }
    assert payload[0]["source"] == "play"
    assert payload[0]["bucket"] == "complaint"
    assert payload[0]["severity"] == 3
    assert payload[0]["l2_theme"] == "refund_not_processed"


def test_deck_spec_emits_frozen_contract_b_slides():
    company, run, reviews, themes = sample_objects()
    deck = build_deck_spec(company, run, reviews, themes)
    assert "# Deck Spec - Example Pay" in deck
    assert "## Slide 1 - About the applicant + project + headline finding" in deck
    assert "## Slide 2 - The data" in deck
    assert "## Slide 3 - Representative voices" in deck
    assert "## Slide 4 - Prioritized problem + proposed solution" in deck
    assert "Payments & refunds." in deck
    assert "L2 breakdown for top complaint/feature themes" in deck
    assert "Refunds: not processed." in deck
    assert "Money was debited but payment was not received" in deck


def test_theme_humanizer_does_not_mangle_overpriced_labels():
    assert humanize_theme("pricing_overd_products_compared_to_competitors") == "Pricing: overpriced products compared to competitors."
    assert humanize_theme("overd_products_compared_to_competitors") == "Pricing: overpriced products compared to competitors."
    assert humanize_theme("unfair_refund_policies_and_failure_to_process_refunds") == "Refunds: unfair policies & failures to process."
