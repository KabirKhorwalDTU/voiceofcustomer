from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import Actor
from app.models import Base, Review
from app.repository import (
    create_public_share_token,
    create_run,
    get_public_shared_run,
    promote_reclassified_share,
    queue_reclassification_from_run,
)
from app.schemas import SubmitRunRequest


def test_reclassification_keeps_source_report_until_verified_promotion():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    owner = Actor(guest_id="original-browser")
    stranger = Actor(guest_id="another-browser")

    with session_factory() as session:
        source, _ = create_run(
            session,
            SubmitRunRequest(name="Airtel", selected_sources=["play", "reddit"]),
            owner,
        )
        source.status = "done"
        session.add(
            Review(
                run_id=source.id,
                company_id=source.company_id,
                review_hash="review-1",
                source="play",
                text="Airtel network drops every call at my home.",
                language="en",
                rating=1,
                theme="network",
            )
        )
        session.flush()
        token = create_public_share_token(session, source.id, owner)

        try:
            queue_reclassification_from_run(session, source.id, stranger)
            assert False, "a different visitor must not reclassify this report"
        except KeyError:
            pass

        replacement, existing = queue_reclassification_from_run(session, source.id, owner)
        assert not existing
        assert replacement.reprocess_from_id == source.id
        assert replacement.public_share_token is None
        assert get_public_shared_run(session, token).id == source.id
        assert queue_reclassification_from_run(session, source.id, owner)[1]

        try:
            promote_reclassified_share(session, replacement.id, owner)
            assert False, "an unfinished report must never replace the public report"
        except ValueError:
            pass

        replacement.status = "done"
        replacement.report_snapshot = {"version": 1, "summary": {"total_reviews": 1, "low_confidence": False}}
        replacement.quarantine_rate = 0
        assert promote_reclassified_share(session, replacement.id, owner) == token
        assert source.public_share_token is None
        assert get_public_shared_run(session, token).id == replacement.id
        assert promote_reclassified_share(session, replacement.id, owner) == token


def test_low_confidence_replacement_cannot_take_public_link():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    owner = Actor(guest_id="original-browser")
    with session_factory() as session:
        source, _ = create_run(session, SubmitRunRequest(name="Airtel"), owner)
        source.status = "done"
        session.add(
            Review(
                run_id=source.id,
                company_id=source.company_id,
                review_hash="review-1",
                source="play",
                text="Airtel network drops every call at my home.",
                language="en",
                rating=1,
            )
        )
        session.flush()
        token = create_public_share_token(session, source.id, owner)
        replacement, _ = queue_reclassification_from_run(session, source.id, owner)
        replacement.status = "done"
        replacement.report_snapshot = {"version": 1, "summary": {"total_reviews": 1, "low_confidence": True}}
        try:
            promote_reclassified_share(session, replacement.id, owner)
            assert False, "a low confidence report must not become public"
        except ValueError:
            pass
        assert get_public_shared_run(session, token).id == source.id
