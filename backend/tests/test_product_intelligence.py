from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import Actor
from app.models import Base, Company, Review, Run, Theme, User
from app.pipeline.synth import build_summary
from app.repository import can_access_run, grant_legacy_kabir_workspace, list_actor_runs


def test_feedback_risk_is_scoped_to_rated_selected_feedback() -> None:
    company = Company(id="company-1", name="Example", brand_keyword="example")
    run = Run(id="run-1", company_id=company.id, company=company, completeness={})
    reviews = [
        Review(id="review-1", run_id=run.id, company_id=company.id, review_hash="one", source="play", date=date.today(), rating=1, text="Broken payments", language="en", theme="payments"),
        Review(id="review-2", run_id=run.id, company_id=company.id, review_hash="two", source="reddit", date=date.today(), rating=None, text="Brand mention", language="en", theme="payments"),
    ]
    themes = [Theme(id="theme-1", run_id=run.id, company_id=company.id, theme="payments", count=2, normalized_frequency=1, avg_severity=0, theme_score=1, rank=1, top_quotes=[], l2_subthemes=[])]

    risk = build_summary(run, reviews, themes)["feedback_risk"]

    assert risk["score"] == 100
    assert risk["label"] == "Customer feedback risk"
    assert "selected public feedback" in risk["scope"]


def test_legacy_workspace_grants_only_snapshot_unowned_history() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with Session() as session:
        kabir = User(id="user-k", email="kabirkhorwal2001@gmail.com")
        another = User(id="user-a", email="other@example.com")
        company = Company(id="company-1", name="Legacy", brand_keyword="legacy")
        legacy = Run(id="run-legacy", company_id=company.id, company=company)
        owned = Run(id="run-owned", company_id=company.id, owner_user_id=another.id, company=company)
        session.add_all([kabir, another, company, legacy, owned])
        session.flush()

        assert grant_legacy_kabir_workspace(session, kabir.id) == 1
        actor = Actor(user_id=kabir.id)
        visible = {run.id for run in list_actor_runs(session, actor)}

        assert visible == {legacy.id}
        assert can_access_run(legacy, actor, session) is True
        assert can_access_run(owned, actor, session) is False
