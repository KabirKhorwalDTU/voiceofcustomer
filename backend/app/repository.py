import calendar
import secrets
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, case, cast, delete, desc, func, or_, select, String
from sqlalchemy.orm import Session, joinedload

from app.auth import Actor
from app.models import ApiUsageDaily, Company, EgressWarning, LegacyRunAccess, Review, Run, RunLog, Settings, Theme, User
from app.onboarding import normalize_business_type, normalize_sources, selected_sources_for_company
from app.pipeline.resolver import ResolvedLinks, resolve_links
from app.schemas import SubmitRunRequest


ACTIVE_STATUSES = ("queued", "scraping", "classifying")
LEGACY_WORKSPACE_EMAIL = "kabirkhorwal2001@gmail.com"
BYTES_PER_GB = 1_000_000_000
EGRESS_WARNING_THRESHOLDS_GB = (2.0, 3.5, 4.5)


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


def actor_run_visibility_filters(actor: Optional[Actor]):
    """Return the same run visibility contract used by every run collection."""
    if actor is None or actor.is_operator:
        return []
    if actor.user_id:
        granted_runs = select(LegacyRunAccess.run_id).where(LegacyRunAccess.user_id == actor.user_id)
        return [or_(Run.owner_user_id == actor.user_id, Run.id.in_(granted_runs))]
    return actor_filters(Run, actor)


def is_legacy_workspace_actor(session: Session, actor: Optional[Actor]) -> bool:
    if not actor or not actor.user_id:
        return False
    email = session.execute(select(User.email).where(User.id == actor.user_id)).scalar_one_or_none()
    return bool(email and email.strip().lower() == LEGACY_WORKSPACE_EMAIL)


def can_access_run(run: Run, actor: Optional[Actor], session: Optional[Session] = None) -> bool:
    if actor is not None and actor.is_operator:
        return True
    if actor is None:
        return False
    if run.owner_user_id and actor.user_id == run.owner_user_id:
        return True
    if run.guest_id and actor.guest_id == run.guest_id and not run.owner_user_id:
        return True
    if session and actor.user_id:
        granted = session.execute(
            select(LegacyRunAccess.id).where(LegacyRunAccess.run_id == run.id, LegacyRunAccess.user_id == actor.user_id)
        ).scalar_one_or_none()
        if granted:
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
            analysis_focus=request.analysis_focus.strip()[:600] or None,
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
        company.analysis_focus = request.analysis_focus.strip()[:600] or None
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
            "analysis_focus": company.analysis_focus or "",
            "maps_url_supplied": bool(company.maps_url),
            "instagram_url_supplied": bool(company.instagram_url),
            "twitter_url_supplied": bool(company.twitter_url),
            "mouthshut_url_supplied": bool(company.mouthshut_url),
        },
    )
    return run, False


def rerun_company_from_run(session: Session, run_id: str, actor: Optional[Actor] = None) -> Tuple[Run, bool]:
    source_run = get_run(session, run_id)
    if not source_run or not can_access_run(source_run, actor, session):
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
        owner_user_id=actor.user_id if actor and actor.user_id else source_run.owner_user_id,
        guest_id=(actor.guest_id if actor and actor.guest_id and not actor.user_id else source_run.guest_id),
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
            "analysis_focus": company.analysis_focus or "",
        },
    )
    return run, False


def delete_run_by_id(session: Session, run_id: str, actor: Optional[Actor] = None) -> bool:
    run = get_run(session, run_id)
    if not run:
        return False
    # Legacy history is mirrored read-only. A rerun creates an owned copy;
    # deleting a historical operator run must remain impossible from /app.
    owned_by_actor = bool(
        actor
        and ((actor.user_id and run.owner_user_id == actor.user_id) or (actor.guest_id and run.guest_id == actor.guest_id and not run.owner_user_id))
    )
    if not owned_by_actor:
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


def list_visible_runs_page(
    session: Session,
    actor: Optional[Actor],
    page: int = 1,
    page_size: int = 25,
    query: str = "",
) -> Tuple[List[Run], int]:
    """Return only the requested workspace page; dashboard history is never bulk-loaded."""
    page = max(1, page)
    page_size = max(1, min(page_size, 50))
    filters = actor_run_visibility_filters(actor)
    statement = select(Run).join(Run.company).where(*filters)
    if query.strip():
        needle = f"%{query.strip()}%"
        statement = statement.where(
            or_(
                Company.name.ilike(needle),
                Company.domain.ilike(needle),
                Run.id.ilike(needle),
                cast(Run.status, String).ilike(needle),
            )
        )
    total = int(session.execute(select(func.count()).select_from(statement.subquery())).scalar_one())
    rows = list(
        session.execute(
            statement.options(joinedload(Run.company)).order_by(desc(Run.created_at)).limit(page_size).offset((page - 1) * page_size)
        ).scalars()
    )
    return rows, total


def list_actor_runs(session: Session, actor: Actor, limit: int = 250) -> List[Run]:
    filters = actor_run_visibility_filters(actor)
    return list(
        session.execute(
            select(Run)
            .where(*filters)
            .options(joinedload(Run.company))
            .order_by(desc(Run.created_at))
            .limit(limit)
        ).scalars()
    )


def get_actor_run_statuses(session: Session, actor: Optional[Actor], run_ids: List[str]) -> List[Run]:
    if not run_ids:
        return []
    return list(
        session.execute(
            select(Run)
            .where(Run.id.in_(run_ids), *actor_run_visibility_filters(actor))
            .options(joinedload(Run.company))
            .order_by(desc(Run.created_at))
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


def create_public_share_token(session: Session, run_id: str, actor: Optional[Actor] = None) -> str:
    """Create one stable, opaque public link for a finished report."""
    run = get_run(session, run_id)
    if not run or not can_access_run(run, actor, session):
        raise KeyError("run not found")
    if run.status not in {"done", "partial"}:
        raise ValueError("only completed or partial reports can be shared")
    if run.public_share_token:
        return run.public_share_token
    for _ in range(5):
        token = secrets.token_urlsafe(24)
        exists = session.execute(select(Run.id).where(Run.public_share_token == token)).scalar_one_or_none()
        if not exists:
            run.public_share_token = token
            session.flush()
            return token
    raise RuntimeError("could not create a unique share link")


def get_public_shared_run(session: Session, token: str) -> Optional[Run]:
    """Public reports are intentionally immutable and terminal-only."""
    return session.execute(
        select(Run)
        .where(Run.public_share_token == token, Run.status.in_(("done", "partial")))
        .options(joinedload(Run.company))
    ).scalars().first()


def get_run_results(session: Session, run_id: str, actor: Optional[Actor] = None) -> Tuple[Run, Company, List[Review], List[Theme]]:
    run = get_run(session, run_id)
    if not run or not can_access_run(run, actor, session):
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
    if not run or not can_access_run(run, actor, session):
        raise KeyError("run not found")
    return _query_reviews_for_run(session, run.id, page=page, page_size=page_size, source=source, theme=theme, l2_theme=l2_theme, rating=rating, review_hash=review_hash, date_query=date_query, text_query=text_query, q=q)


def _query_reviews_for_run(
    session: Session,
    run_id: str,
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


def query_public_shared_reviews(
    session: Session,
    token: str,
    **filters: Any,
) -> Tuple[List[Review], int]:
    run = get_public_shared_run(session, token)
    if not run:
        raise KeyError("shared report not found")
    # Use the same pagination and column filtering as the private report, but
    # authorize through the opaque share token instead of a workspace session.
    return _query_reviews_for_run(session, run.id, **filters)


def get_company_runs(session: Session, company_id: str, actor: Optional[Actor] = None) -> List[Run]:
    filters = actor_run_visibility_filters(actor)
    return list(
        session.execute(
            select(Run).where(Run.company_id == company_id, *filters).options(joinedload(Run.company)).order_by(desc(Run.created_at))
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


def grant_legacy_kabir_workspace(session: Session, user_id: str) -> int:
    """One-way visibility grants for historical pre-workspace runs only."""
    user = session.get(User, user_id)
    if not user or user.email.strip().lower() != LEGACY_WORKSPACE_EMAIL:
        return 0
    legacy_ids = session.execute(
        select(Run.id).where(Run.owner_user_id.is_(None), Run.guest_id.is_(None))
    ).scalars().all()
    if not legacy_ids:
        return 0
    granted_ids = set(
        session.execute(
            select(LegacyRunAccess.run_id).where(LegacyRunAccess.user_id == user_id, LegacyRunAccess.run_id.in_(legacy_ids))
        ).scalars()
    )
    for run_id in legacy_ids:
        if run_id not in granted_ids:
            session.add(LegacyRunAccess(run_id=run_id, user_id=user_id))
    session.flush()
    return len(legacy_ids) - len(granted_ids)


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


def billing_cycle_bounds(now: Optional[datetime] = None, cycle_day: int = 24) -> Tuple[date, date]:
    """Return UTC billing bounds; Supabase usage reporting is UTC based."""
    current = (now or datetime.now(timezone.utc)).date()
    cycle_day = max(1, min(int(cycle_day), 28))

    def anchored(year: int, month: int) -> date:
        return date(year, month, min(cycle_day, calendar.monthrange(year, month)[1]))

    current_anchor = anchored(current.year, current.month)
    if current >= current_anchor:
        start = current_anchor
    elif current.month == 1:
        start = anchored(current.year - 1, 12)
    else:
        start = anchored(current.year, current.month - 1)
    if start.month == 12:
        end = anchored(start.year + 1, 1)
    else:
        end = anchored(start.year, start.month + 1)
    return start, end


def persist_api_usage(
    session: Session,
    buckets: Dict[Tuple[date, str, int], Tuple[int, int]],
    cycle_day: int = 24,
    now: Optional[datetime] = None,
) -> List[EgressWarning]:
    """Merge an in-process metrics batch and create each budget warning once."""
    for (usage_date, endpoint, status_code), (request_count, response_bytes) in buckets.items():
        row = session.execute(
            select(ApiUsageDaily).where(
                ApiUsageDaily.usage_date == usage_date,
                ApiUsageDaily.endpoint == endpoint,
                ApiUsageDaily.status_code == status_code,
            )
        ).scalars().first()
        if row is None:
            row = ApiUsageDaily(
                usage_date=usage_date,
                endpoint=endpoint,
                status_code=status_code,
                request_count=int(request_count),
                response_body_bytes=int(response_bytes),
            )
            session.add(row)
        else:
            row.request_count += int(request_count)
            row.response_body_bytes += int(response_bytes)
    session.flush()

    cycle_start, cycle_end = billing_cycle_bounds(now=now, cycle_day=cycle_day)
    estimated_bytes = int(
        session.execute(
            select(func.coalesce(func.sum(ApiUsageDaily.response_body_bytes), 0)).where(
                ApiUsageDaily.usage_date >= cycle_start,
                ApiUsageDaily.usage_date < cycle_end,
            )
        ).scalar_one()
        or 0
    )
    emitted = {
        int(value)
        for value in session.execute(
            select(EgressWarning.threshold_bytes).where(EgressWarning.cycle_start == cycle_start)
        ).scalars()
    }
    warnings: List[EgressWarning] = []
    for threshold_gb in EGRESS_WARNING_THRESHOLDS_GB:
        threshold_bytes = int(threshold_gb * BYTES_PER_GB)
        if estimated_bytes < threshold_bytes or threshold_bytes in emitted:
            continue
        warning = EgressWarning(
            cycle_start=cycle_start,
            threshold_bytes=threshold_bytes,
            estimated_bytes=estimated_bytes,
        )
        session.add(warning)
        warnings.append(warning)
    session.flush()
    return warnings


def get_egress_usage(session: Session, cycle_day: int = 24, now: Optional[datetime] = None) -> Tuple[date, date, int, List[ApiUsageDaily], List[EgressWarning]]:
    cycle_start, cycle_end = billing_cycle_bounds(now=now, cycle_day=cycle_day)
    entries = list(
        session.execute(
            select(ApiUsageDaily)
            .where(ApiUsageDaily.usage_date >= cycle_start, ApiUsageDaily.usage_date < cycle_end)
            .order_by(desc(ApiUsageDaily.response_body_bytes), ApiUsageDaily.endpoint)
        ).scalars()
    )
    total = sum(int(row.response_body_bytes or 0) for row in entries)
    warnings = list(
        session.execute(
            select(EgressWarning).where(EgressWarning.cycle_start == cycle_start).order_by(EgressWarning.threshold_bytes)
        ).scalars()
    )
    return cycle_start, cycle_end, total, entries, warnings
