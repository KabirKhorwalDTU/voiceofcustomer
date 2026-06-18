from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import Actor, create_or_get_user
from app.models import Base
from app.repository import claim_guest_workspace, create_run, list_actor_runs
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
