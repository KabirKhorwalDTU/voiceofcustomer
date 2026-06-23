from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import Actor
from app.main import get_or_create_report_snapshot, run_list_item_out, run_status_out
from app.models import Base, Company, Review, Run, Theme, User
from app.pipeline.synth import export_reviews
from app.repository import get_egress_usage, list_visible_runs_page, persist_api_usage, query_run_reviews


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()


def test_workspace_page_is_scoped_paginated_and_lean() -> None:
    session = make_session()
    user = User(id="user-1", email="founder@example.com")
    company = Company(id="company-1", owner_user_id=user.id, name="Example", brand_keyword="example", selected_sources=["play", "maps"])
    session.add_all([user, company])
    session.flush()
    for index in range(30):
        session.add(Run(id=f"run-{index}", company_id=company.id, owner_user_id=user.id, company=company, status="done"))
    session.flush()

    rows, total = list_visible_runs_page(session, Actor(user_id=user.id), page=2, page_size=25)

    assert total == 30
    assert len(rows) == 5
    payload = run_list_item_out(session, rows[0]).model_dump()
    assert set(payload) == {
        "id", "company_id", "status", "model_used", "cost_estimate", "budget_cap", "quarantine_rate",
        "started_at", "finished_at", "created_at", "company", "current_stage", "stage_detail", "progress",
    }
    assert payload["company"] == {"id": company.id, "name": "Example", "domain": None, "selected_sources": ["play", "maps"]}


def test_status_shape_stays_small_and_exposes_only_live_fields() -> None:
    session = make_session()
    company = Company(id="company-1", guest_id="guest-1234567890", name="Example", brand_keyword="example")
    run = Run(
        id="run-1",
        company_id=company.id,
        guest_id=company.guest_id,
        company=company,
        status="classifying",
        completeness={"play": {"status": "ok", "count": 20}, "maps": {"status": "disabled"}},
    )
    session.add_all([company, run])
    session.flush()

    payload = run_status_out(session, run).model_dump()

    assert payload["source_states"] == {"play": "ok", "maps": "disabled"}
    assert "completeness" not in payload
    assert "company" not in payload


def test_terminal_legacy_report_is_snapshotted_once() -> None:
    session = make_session()
    company = Company(id="company-1", guest_id="guest-1234567890", name="Example", brand_keyword="example")
    run = Run(id="run-1", company_id=company.id, guest_id=company.guest_id, company=company, status="done", completeness={"play": {"status": "ok"}})
    review = Review(
        id="review-1", run_id=run.id, company_id=company.id, review_hash="hash-1", source="play",
        date=date(2026, 6, 1), rating=1, text="Payments fail", language="en", theme="payment_failures", l2_theme="card_declined",
    )
    theme = Theme(
        id="theme-1", run_id=run.id, company_id=company.id, theme="payment_failures", count=1,
        normalized_frequency=1, avg_severity=0, theme_score=1, rank=1, top_quotes=[],
        l2_subthemes=[{"label": "card_declined", "count": 1, "score": 1, "top_quotes": []}],
    )
    session.add_all([company, run, review, theme])
    session.flush()

    snapshot = get_or_create_report_snapshot(session, run, Actor(guest_id=company.guest_id))
    repeated = get_or_create_report_snapshot(session, run, Actor(guest_id=company.guest_id))

    assert snapshot["version"] == 1
    assert snapshot["summary"]["total_reviews"] == 1
    assert snapshot["themes"][0]["theme"] == "payment_failures"
    assert repeated == snapshot
    assert run.report_snapshot == snapshot


def test_egress_usage_aggregates_by_endpoint_and_warns_once_per_cycle() -> None:
    session = make_session()
    now = datetime(2026, 6, 23, tzinfo=timezone.utc)
    usage_date = now.date()

    first = persist_api_usage(session, {(usage_date, "/api/runs", 200): (10, 2_100_000_000)}, cycle_day=24, now=now)
    second = persist_api_usage(session, {(usage_date, "/api/runs/status", 200): (10, 1_600_000_000)}, cycle_day=24, now=now)
    third = persist_api_usage(session, {(usage_date, "/api/runs", 200): (1, 1)}, cycle_day=24, now=now)
    cycle_start, cycle_end, total, entries, warnings = get_egress_usage(session, cycle_day=24, now=now)

    assert [warning.threshold_bytes for warning in first] == [2_000_000_000]
    assert [warning.threshold_bytes for warning in second] == [3_500_000_000]
    assert third == []
    assert cycle_start == date(2026, 5, 24)
    assert cycle_end == date(2026, 6, 24)
    assert total == 3_700_000_001
    assert sum(row.request_count for row in entries) == 21
    assert [warning.threshold_bytes for warning in warnings] == [2_000_000_000, 3_500_000_000]


def test_review_column_filters_and_all_exports_work_with_real_rows() -> None:
    session = make_session()
    company = Company(id="company-1", guest_id="guest-1234567890", name="Example", brand_keyword="example")
    run = Run(id="run-1", company_id=company.id, guest_id=company.guest_id, company=company, status="done")
    payment = Review(
        id="review-1", run_id=run.id, company_id=company.id, review_hash="payment-hash", source="play",
        date=date(2026, 6, 20), rating=1, text="Payment failed at checkout", language="en",
        theme="payments_or_refunds", l2_theme="card_declined",
    )
    delivery = Review(
        id="review-2", run_id=run.id, company_id=company.id, review_hash="delivery-hash", source="appstore",
        date=date(2026, 6, 19), rating=2, text="Delivery came late", language="en",
        theme="delivery_or_service_fulfillment", l2_theme="late_arrival",
    )
    session.add_all([company, run, payment, delivery])
    session.flush()
    actor = Actor(guest_id=company.guest_id)

    checks = [
        {"source": "play"},
        {"rating": "1"},
        {"review_hash": "payment"},
        {"date_query": "2026-06-20"},
        {"theme": "payments_or_refunds"},
        {"l2_theme": "card_declined"},
        {"text_query": "checkout"},
    ]
    for filters in checks:
        rows, total = query_run_reviews(session, run.id, actor=actor, **filters)
        assert total == 1
        assert rows == [payment]

    for fmt, media_type, filename in [
        ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "tagged_reviews.xlsx"),
        ("csv", "text/csv", "tagged_reviews.csv"),
        ("json", "application/json", "tagged_reviews.json"),
    ]:
        body, actual_media_type, actual_filename = export_reviews([payment, delivery], fmt)
        assert body
        assert actual_media_type == media_type
        assert actual_filename == filename
