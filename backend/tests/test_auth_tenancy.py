from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import Actor, create_or_get_user
from app.models import Base
from app.repository import (
    can_access_run,
    claim_guest_workspace,
    create_public_share_token,
    create_run,
    get_public_shared_run,
    list_actor_runs,
    query_public_shared_reviews,
)
from app.models import Review
from app.schemas import SubmitRunRequest


def make_request(name: str) -> SubmitRunRequest:
    slug = name.lower().replace(" ", "")
    return SubmitRunRequest(
        name=name,
        play_link=f"https://play.google.com/store/apps/details?id=com.example.{slug}",
        app_store_link=f"https://apps.apple.com/in/app/{slug}/id123456789",
        website=f"https://{slug}.com",
        maps_enabled=True,
        maps_location_hint="India",
        reddit_enabled=True,
    )


def test_guest_and_user_runs_are_tenant_scoped_and_claimable():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with SessionLocal() as session:
        guest_a = Actor(guest_id="guest-a-workspace")
        guest_b = Actor(guest_id="guest-b-workspace")

        run_a, _ = create_run(session, make_request("Example Pay"), guest_a)
        run_b, _ = create_run(session, make_request("Example Pay"), guest_b)
        session.commit()

        assert run_a.id != run_b.id
        assert [run.id for run in list_actor_runs(session, guest_a)] == [run_a.id]
        assert [run.id for run in list_actor_runs(session, guest_b)] == [run_b.id]

        user = create_or_get_user(session, "founder@example.com")
        claimed = claim_guest_workspace(session, "guest-a-workspace", user.id)
        session.commit()

        assert claimed == 1
        assert list_actor_runs(session, guest_a) == []
        assert [run.id for run in list_actor_runs(session, Actor(user_id=user.id))] == [run_a.id]
        assert [run.id for run in list_actor_runs(session, guest_b)] == [run_b.id]


def test_finished_report_can_be_shared_without_granting_workspace_access():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with SessionLocal() as session:
        owner = Actor(guest_id="guest-share-owner")
        run, _ = create_run(session, make_request("Shareable Example"), owner)
        run.status = "done"
        session.add(
            Review(
                run_id=run.id,
                company_id=run.company_id,
                review_hash="public-review-hash",
                source="play",
                text="Checkout failed after payment.",
                language="en",
                rating=1,
                theme="payments",
            )
        )
        session.flush()

        token = create_public_share_token(session, run.id, owner)
        assert create_public_share_token(session, run.id, owner) == token
        assert len(token) >= 30
        assert not can_access_run(run, Actor(guest_id="different-browser"), session)
        assert get_public_shared_run(session, token).id == run.id

        rows, total = query_public_shared_reviews(session, token, text_query="Checkout")
        assert total == 1
        assert rows[0].review_hash == "public-review-hash"
        assert get_public_shared_run(session, "not-a-real-share-token") is None
