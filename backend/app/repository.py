from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, case, cast, delete, desc, func, or_, select, String
from sqlalchemy.orm import Session, joinedload

from app.auth import Actor
from app.models import Company, Review, Run, RunLog, Settings, Theme
from app.onboarding import normalize_business_type, normalize_sources, selected_sources_for_company
from app.pipeline.resolver import ResolvedLinks, resolve_links
from app.schemas import SubmitRunRequest


ACTIVE_STATUSES = ("queued", "scraping", "classifying")


def get_settings(session: Session) -> Settings:
    settings = session.get(Settings, 1)
    if settings is None:
        settings = Settings(id=1)
        session.add(settings)
        session.flush()
    return settings


def update_settings(session: Session, values: Dict[str, Any]) -> Settings:
    settings = get_settings(session)
    for key, value in values.items():
        if value is not None and hasattr(settings, key):
            setattr(settings, key, value)
    session.flush()
    return settings


def actor_filters(model, actor: Optional[Actor]):
    if actor is None or actor.is_operator:
        return []
    if actor.user_id:
        return [model.owner_user_id == actor.user_id]
    if actor.guest_id:
        return [model.guest_id == actor.guest_id, model.owner_user_id.is_(None)]
    return [model.owner_user_id.is_(None), model.guest_id.is_(None)]


def can_access_run(run: Run, actor: Optional[Actor]) -> bool:
    if actor is not None and actor.is_operator:
        return True
    if actor is None:
        return False
    if not run.owner_user_id and not run.guest_id:
        return False
    if run.owner_user_id and actor.user_id == run.owner_user_id:
        return True
    if run.guest_id and actor.guest_id == run.guest_id and not run.owner_user_id:
        return True
    return False


def find_matching_company(session: Session, request: SubmitRunRequest, actor: Optional[Actor] = None) -> Tuple[ResolvedLinks, Optional[Company]]:
    resolved = resolve_links(request.play_link, request.app_store_link, request.website, request.name)
    clauses = []
    if resolved.play_id:
        clauses.append(Company.play_id == resolved.play_id)
    if resolved.app_id:
        clauses.append(Company.app_id == resolved.app_id)
    if resolved.domain:
        clauses.append(and_(Company.domain == resolved.domain, Company.name == request.name.strip()))
    filters = actor_filters(Company, actor)
    company = session.execute(select(Company).where(or_(*clauses), *filters)).scalars().first() if clauses else None
    return resolved, company


def create_or_get_company(
    session: Session,
    request: SubmitRunRequest,
    actor: Optional[Actor] = None,
    resolved: Optional[ResolvedLinks] = None,
    existing_company: Optional[Company] = None,
) -> Company:
    if resolved is None:
        resolved, existing_company = find_matching_company(session, request, actor)
    business_type = normalize_business_type(request.business_type)
    requested_sources = list(request.selected_sources)
    # Keep older API clients functional while the public UI moves to source chips.
    if not requested_sources:
        if request.maps_enabled:
            requested_sources.append("maps")
        if request.reddit_enabled:
            requested_sources.append("reddit")
    selected_sources = normalize_sources(requested_sources, business_type)
    maps_enabled = "maps" in selected_sources
    reddit_enabled = "reddit" in selected_sources
    company = existing_company
    if company is None:
        company = Company(
            owner_user_id=actor.user_id if actor and actor.user_id else None,
            guest_id=actor.guest_id if actor and actor.guest_id and not actor.user_id else None,
            name=request.name.strip(),
            play_id=resolved.play_id or None,
            app_id=resolved.app_id or None,
            domain=resolved.domain or None,
            brand_keyword=resolved.brand_keyword,
            maps_enabled=maps_enabled,
            maps_location_hint=request.maps_location_hint.strip() or "India",
            reddit_enabled=reddit_enabled,
            business_type=business_type,
            selected_sources=selected_sources,
            analysis_goals=list(dict.fromkeys(request.analysis_goals))[:8],
            maps_url=request.maps_url.strip() or None,
            instagram_url=request.instagram_url.strip() or None,
            twitter_url=request.twitter_url.strip() or None,
            mouthshut_url=request.mouthshut_url.strip() or None,
        )
        session.add(company)
        session.flush()
    else:
        company.name = request.name.strip()
        company.play_id = company.play_id or resolved.play_id or None
        company.app_id = company.app_id or resolved.app_id or None
        company.domain = company.domain or resolved.domain or None
        company.brand_keyword = resolved.brand_keyword or company.brand_keyword
        company.maps_enabled = maps_enabled
        company.maps_location_hint = request.maps_location_hint.strip() or company.maps_location_hint or "India"
        company.reddit_enabled = reddit_enabled
        company.business_type = business_type
        company.selected_sources = selected_sources
        company.analysis_goals = list(dict.fromkeys(request.analysis_goals))[:8]
        company.maps_url = request.maps_url.strip() or None
        company.instagram_url = request.instagram_url.strip() or None
        company.twitter_url = request.twitter_url.strip() or None
        company.mouthshut_url = request.mouthshut_url.strip() or None
    return company


def create_run(session: Session, request: SubmitRunRequest, actor: Optional[Actor] = None) -> Tuple[Run, bool]:
    resolved, existing_company = find_matching_company(session, request, actor)
    active = None
    if existing_company is not None:
        active = session.execute(
            select(Run)
            .where(Run.company_id == existing_company.id, Run.status.in_(ACTIVE_STATUSES), *actor_filters(Run, actor))
            .options(joinedload(Run.company))
            .order_by(desc(Run.created_at))
        ).scalars().first()
    if active:
        log_run_event(
            session,
            active,
            stage="queue",
            event="deduped_existing_run",
            status="ok",
            details={"reason": "company already has an active run"},
        )
        return active, True
    company = create_or_get_company(session, request, actor, resolved=resolved, existing_company=existing_company)
    settings = get_settings(session)
    run = Run(
        company_id=company.id,
        owner_user_id=actor.user_id if actor and actor.user_id else None,
        guest_id=actor.guest_id if actor and actor.guest_id and not actor.user_id else None,
        status="queued",
        budget_cap=float(settings.per_run_budget_usd),
        company=company,
    )
    session.add(run)
    session.flush()
    log_run_event(
        session,
        run,
        stage="queue",
        event="run_queued",
        status="ok",
        details={
            "company_name": company.name,
            "play_id": company.play_id,
            "app_id": company.app_id,
            "domain": company.domain,
            "brand_keyword": company.brand_keyword,
            "maps_enabled": company.maps_enabled,
            "maps_location_hint": company.maps_location_hint,
            "reddit_enabled": company.reddit_enabled,
            "business_type": company.business_type,
            "selected_sources": selected_sources_for_company(company),
            "analysis_goals": company.analysis_goals or [],
            "maps_url_supplied": bool(company.maps_url),
            "instagram_url_supplied": bool(company.instagram_url),
            "twitter_url_supplied": bool(company.twitter_url),
            "mouthshut_url_supplied": bool(company.mouthshut_url),
        },
    )
    return run, False


def rerun_company_from_run(session: Session, run_id: str, actor: Optional[Actor] = None) -> Tuple[Run, bool]:
    source_run = get_run(session, run_id)
    if not source_run or not can_access_run(source_run, actor):
        raise KeyError("run not found")
    company = source_run.company
    active = session.execute(
        select(Run)
        .where(Run.company_id == company.id, Run.status.in_(ACTIVE_STATUSES), *actor_filters(Run, actor))
        .options(joinedload(Run.company))
        .order_by(desc(Run.created_at))
    ).scalars().first()
    if active:
        log_run_event(
            session,
            active,
            stage="queue",
            event="deduped_existing_rerun",
            status="ok",
            details={"reason": "company already has an active run", "source_run_id": run_id},
        )
        return active, True
    settings = get_settings(session)
    run = Run(
        company_id=company.id,
        owner_user_id=source_run.owner_user_id,
        guest_id=source_run.guest_id,
        status="queued",
        budget_cap=float(settings.per_run_budget_usd),
        company=company,
    )
    session.add(run)
    session.flush()
    log_run_event(
        session,
        run,
        stage="queue",
        event="run_requeued",
        status="ok",
        details={
            "source_run_id": run_id,
            "company_name": company.name,
            "play_id": company.play_id,
            "app_id": company.app_id,
            "domain": company.domain,
            "brand_keyword": company.brand_keyword,
            "maps_enabled": company.maps_enabled,
            "maps_location_hint": company.maps_location_hint,
            "reddit_enabled": company.reddit_enabled,
            "business_type": company.business_type,
            "selected_sources": selected_sources_for_company(company),
            "analysis_goals": company.analysis_goals or [],
        },
    )
    return run, False


def delete_run_by_id(session: Session, run_id: str, actor: Optional[Actor] = None) -> bool:
    run = get_run(session, run_id)
    if not run:
        return False
    if not can_access_run(run, actor):
        return False
    if run.status in ACTIVE_STATUSES:
        raise ValueError("active runs cannot be deleted")
    session.execute(delete(RunLog).where(RunLog.run_id == run_id))
    session.execute(delete(Theme).where(Theme.run_id == run_id))
    session.execute(delete(Review).where(Review.run_id == run_id))
    session.delete(run)
    session.flush()
    return True


def list_runs(session: Session, limit: int = 250) -> List[Run]:
    return list(
        session.execute(
            select(Run).options(joinedload(Run.company)).order_by(desc(Run.created_at)).limit(limit)
        ).scalars()
    )


def list_actor_runs(session: Session, actor: Actor, limit: int = 250) -> List[Run]:
    return list(
        session.execute(
            select(Run)
            .where(*actor_filters(Run, actor))
            .options(joinedload(Run.company))
            .order_by(desc(Run.created_at))
            .limit(limit)
        ).scalars()
    )


def get_latest_run_logs(session: Session, run_ids: List[str]) -> Dict[str, RunLog]:
    if not run_ids:
        return {}
    latest = (
        select(RunLog.run_id, func.max(RunLog.created_at).label("created_at"))
        .where(RunLog.run_id.in_(run_ids))
        .group_by(RunLog.run_id)
        .subquery()
    )
    rows = list(
        session.execute(
            select(RunLog)
            .join(latest, and_(RunLog.run_id == latest.c.run_id, RunLog.created_at == latest.c.created_at))
            .order_by(desc(RunLog.created_at))
        ).scalars()
    )
    by_run: Dict[str, RunLog] = {}
    for row in rows:
        by_run.setdefault(row.run_id, row)
    return by_run


def get_run(session: Session, run_id: str) -> Optional[Run]:
    return session.execute(select(Run).where(Run.id == run_id).options(joinedload(Run.company))).scalars().first()


def get_run_results(session: Session, run_id: str, actor: Optional[Actor] = None) -> Tuple[Run, Company, List[Review], List[Theme]]:
    run = get_run(session, run_id)
    if not run or not can_access_run(run, actor):
        raise KeyError("run not found")
    company = run.company
    reviews = list(session.execute(select(Review).where(Review.run_id == run_id).order_by(desc(Review.date))).scalars())
    themes = list(session.execute(select(Theme).where(Theme.run_id == run_id).order_by(Theme.rank)).scalars())
    return run, company, reviews, themes


def query_run_reviews(
    session: Session,
    run_id: str,
    actor: Optional[Actor] = None,
    page: int = 1,
    page_size: int = 50,
    source: str = "",
    theme: str = "",
    l2_theme: str = "",
    rating: str = "",
    review_hash: str = "",
    date_query: str = "",
    text_query: str = "",
    q: str = "",
) -> Tuple[List[Review], int]:
    run = get_run(session, run_id)
    if not run or not can_access_run(run, actor):
        raise KeyError("run not found")
    page = max(page, 1)
    page_size = max(1, min(page_size, 100))
    filters = [Review.run_id == run_id]
    if source:
        filters.append(Review.source == source)
    if theme:
        filters.append(Review.theme == theme)
    if l2_theme:
        filters.append(Review.l2_theme == l2_theme)
    if rating:
        try:
            filters.append(Review.rating == int(rating))
        except ValueError:
            filters.append(cast(Review.rating, String).ilike(f"%{rating}%"))
    if review_hash:
        filters.append(Review.review_hash.ilike(f"%{review_hash}%"))
    if date_query:
        filters.append(cast(Review.date, String).ilike(f"%{date_query}%"))
    if text_query:
        filters.append(Review.text.ilike(f"%{text_query}%"))
    if q:
        like = f"%{q}%"
        filters.append(
            or_(
                Review.review_hash.ilike(like),
                cast(Review.source, String).ilike(like),
                cast(Review.date, String).ilike(like),
                cast(Review.rating, String).ilike(like),
                Review.text.ilike(like),
                Review.language.ilike(like),
                Review.theme.ilike(like),
                Review.l2_theme.ilike(like),
            )
        )
    total = int(session.execute(select(func.count()).select_from(Review).where(*filters)).scalar_one())
    rows = list(
        session.execute(
            select(Review)
            .where(*filters)
            .order_by(desc(Review.date), Review.id)
            .limit(page_size)
            .offset((page - 1) * page_size)
        ).scalars()
    )
    return rows, total


def get_company_runs(session: Session, company_id: str, actor: Optional[Actor] = None) -> List[Run]:
    return list(
        session.execute(
            select(Run).where(Run.company_id == company_id, *actor_filters(Run, actor)).options(joinedload(Run.company)).order_by(desc(Run.created_at))
        ).scalars()
    )


def claim_guest_workspace(session: Session, guest_id: str, user_id: str) -> int:
    guest_id = guest_id.strip()
    if not guest_id:
        return 0
    companies = session.execute(select(Company).where(Company.guest_id == guest_id, Company.owner_user_id.is_(None))).scalars().all()
    runs = session.execute(select(Run).where(Run.guest_id == guest_id, Run.owner_user_id.is_(None))).scalars().all()
    for company in companies:
        company.owner_user_id = user_id
        company.guest_id = None
    for run in runs:
        run.owner_user_id = user_id
        run.guest_id = None
    session.flush()
    return len(runs)


def set_run_status(session: Session, run: Run, status: str, error: Optional[str] = None) -> None:
    run.status = status
    if status in {"scraping", "classifying"} and run.started_at is None:
        run.started_at = datetime.now(timezone.utc)
    if status in {"done", "partial", "failed"}:
        run.finished_at = datetime.now(timezone.utc)
    if error:
        run.error = error
    elif status in {"scraping", "classifying", "done", "partial"}:
        run.error = None
    session.flush()


def log_run_event(
    session: Session,
    run: Run,
    stage: str,
    event: str,
    status: str = "info",
    source: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    attempt: Optional[int] = None,
    cost_usd: float = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int = 0,
    details: Optional[Dict[str, Any]] = None,
) -> RunLog:
    row = RunLog(
        run_id=run.id,
        company_id=run.company_id,
        stage=stage,
        event=event,
        status=status,
        source=source,
        provider=provider,
        model=model,
        attempt=attempt,
        cost_usd=cost_usd,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        details=details or {},
    )
    session.add(row)
    session.flush()
    return row


def get_run_logs(session: Session, run_id: str, limit: Optional[int] = None) -> List[RunLog]:
    statement = select(RunLog).where(RunLog.run_id == run_id).order_by(RunLog.created_at)
    if limit:
        statement = statement.limit(limit)
    return list(session.execute(statement).scalars())


def get_latest_run_log(session: Session, run_id: str) -> Optional[RunLog]:
    return session.execute(
        select(RunLog).where(RunLog.run_id == run_id).order_by(desc(RunLog.created_at)).limit(1)
    ).scalars().first()


def get_run_cost_rollup(session: Session, run_id: str) -> Dict[str, Dict[str, float]]:
    rows = session.execute(
        select(
            RunLog.provider,
            func.count(RunLog.id),
            func.sum(RunLog.cost_usd),
            func.sum(RunLog.input_tokens),
            func.sum(RunLog.output_tokens),
            func.sum(RunLog.total_tokens),
            func.sum(case((RunLog.total_tokens > 0, 1), else_=0)),
        )
        .where(RunLog.run_id == run_id, RunLog.provider.is_not(None))
        .group_by(RunLog.provider)
    ).all()
    return {
        provider: {
            "events": int(events or 0),
            "calls": int(calls or 0),
            "cost": float(cost or 0),
            "input_tokens": int(input_tokens or 0),
            "output_tokens": int(output_tokens or 0),
            "tokens": int(total_tokens or 0),
        }
        for provider, events, cost, input_tokens, output_tokens, total_tokens, calls in rows
        if provider
    }
