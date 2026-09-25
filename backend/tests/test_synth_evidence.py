from datetime import date

from app.models import Review, Run
from app.pipeline.synth import build_l2_subtheme_rows, build_theme_rows


def _review(text: str, theme: str, l2_theme: str = "", source: str = "play") -> Review:
    return Review(
        text=text,
        theme=theme,
        l2_theme=l2_theme or None,
        source=source,
        date=date.today(),
        rating=1,
    )


def test_unrelated_l2_reviews_cannot_be_presented_as_representative_evidence():
    examples = [
        ("slow_internet_speeds", "I found a trick in Spotify for BSNL users after my daily data is used."),
        ("frequent_fiber_disconnection", "Jio AirFiber vs Airtel AirFiber? Which is cheaper for WFH?"),
        ("failed_recharge_transactions", "Fastag recharge available for Airtel customers at a discount."),
        ("hidden_overcharges", "Can someone share an Airtel WiFi bill summary for the yearly plan?"),
        ("payment_not_reflecting", "I applied for the Orient IPO and received a mandate message."),
    ]

    for label, text in examples:
        reviews = [_review(text, "airtel_service", label) for _ in range(5)]
        row = build_l2_subtheme_rows(reviews, recency_window_days=365)[0]
        assert row["count"] == 5
        assert row["top_quotes"] == [], label


def test_l2_selects_supported_failure_instead_of_related_product_mention():
    reviews = [
        _review("Jio AirFiber vs Airtel AirFiber? Which is cheaper?", "broadband", "frequent_fiber_disconnection"),
        _review("My Airtel fiber disconnected twice today during work calls.", "broadband", "frequent_fiber_disconnection"),
        _review("The fiber has been down since morning and the router shows LOS.", "broadband", "frequent_fiber_disconnection"),
        _review("I am looking for an Airtel fiber plan.", "broadband", "frequent_fiber_disconnection"),
        _review("Any advice about fiber availability in this town?", "broadband", "frequent_fiber_disconnection"),
    ]

    row = build_l2_subtheme_rows(reviews, recency_window_days=365)[0]
    quotes = [quote["text"] for quote in row["top_quotes"]]
    assert len(quotes) == 2
    assert all("disconnected" in quote or "down" in quote for quote in quotes)


def test_source_size_affects_theme_rank_and_other_is_never_prioritized():
    run = Run(id="run-1", company_id="company-1")
    reviews = (
        [_review("My network has no signal today.", "network_connectivity") for _ in range(60)]
        + [_review("My support ticket remains unresolved.", "customer_support") for _ in range(20)]
        + [_review("My support ticket remains unresolved.", "customer_support", source="reddit")]
        + [_review("Generic unrelated discussion.", "other", source="reddit") for _ in range(5)]
    )

    rows = build_theme_rows(run, reviews, {"play": 1, "reddit": 1}, recency_window_days=365)
    assert [row.theme for row in rows] == ["network_connectivity", "customer_support", "other"]
    assert rows[0].theme_score > rows[1].theme_score
    assert rows[-1].theme_score == 0
    assert rows[-1].count == 5
    assert rows[-1].top_quotes == []
