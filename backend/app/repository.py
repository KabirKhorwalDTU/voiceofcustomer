from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, desc, or_, select
from sqlalchemy.orm import Session, joinedload

from app.models import Company, Review, Run, RunLog, Settings, Theme
from app.pipeline.resolver import resolve_links
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


def create_or_get_company(session: Session, request: SubmitRunRequest) -> Company:
    resolved = resolve_links(request.play_link, request.app_store_link, request.website, request.name)
    clauses = []
    if resolved.play_id:
        clauses.append(Company.play_id == resolved.play_id)
    if resolved.app_id:
        clauses.append(Company.app_id == resolved.app_id)
    if resolved.domain:
        clauses.append(and_(Company.domain == resolved.domain, Company.name == request.name))
    company = session.execute(select(Company).where(or_(*clauses))).scalars().first() if clauses else None
    if company is None:
        company = Company(
            name=request.name.strip(),
            play_id=resolved.play_id or None,
            app_id=resolved.app_id or None,
            domain=resolved.domain or None,
            brand_keyword=resolved.brand_keyword,
            maps_enabled=request.maps_enabled,
            maps_location_hint=request.maps_location_hint.strip() or "India",
        )
        session.add(company)
        session.flush()
    else:
        company.name = request.name.strip()
        company.play_id = company.play_id or resolved.play_id or None
        company.app_id = company.app_id or resolved.app_id or None
        company.domain = company.domain or resolved.domain or None
        company.brand_keyword = resolved.brand_keyword or company.brand_keyword
        company.maps_enabled = request.maps_enabled
        company.maps_location_hint = request.maps_location_hint.strip() or company.maps_location_hint or "India"
    return company


def create_run(session: Session, request: SubmitRunRequest) -> Tuple[Run, bool]:
    company = create_or_get_company(session, request)
    active = session.execute(
        select(Run)
        .where(Run.company_id == company.id, Run.status.in_(ACTIVE_STATUSES))
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
    settings = get_settings(session)
    run = Run(company_id=company.id, status="queued", budget_cap=float(settings.per_run_budget_usd), company=company)
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
        },
    )
    return run, False


def list_runs(session: Session, limit: int = 50) -> List[Run]:
    return list(
        session.execute(
            select(Run).options(joinedload(Run.company)).order_by(desc(Run.created_at)).limit(limit)
        ).scalars()
    )


def get_run(session: Session, run_id: str) -> Optional[Run]:
    return session.execute(select(Run).where(Run.id == run_id).options(joinedload(Run.company))).scalars().first()


def get_run_results(session: Session, run_id: str) -> Tuple[Run, Company, List[Review], List[Theme]]:
    run = get_run(session, run_id)
    if not run:
        raise KeyError("run not found")
    company = run.company
    reviews = list(session.execute(select(Review).where(Review.run_id == run_id).order_by(desc(Review.date))).scalars())
    themes = list(session.execute(select(Theme).where(Theme.run_id == run_id).order_by(Theme.rank)).scalars())
    return run, company, reviews, themes


def get_company_runs(session: Session, company_id: str) -> List[Run]:
    return list(
        session.execute(
            select(Run).where(Run.company_id == company_id).options(joinedload(Run.company)).order_by(desc(Run.created_at))
        ).scalars()
    )


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


def prior_tags_by_hash(session: Session, company_id: str, hashes: List[str]) -> Dict[str, Review]:
    if not hashes:
        return {}
    rows = session.execute(
        select(Review)
        .join(Run, Run.id == Review.run_id)
        .where(
            Review.company_id == company_id,
            Review.review_hash.in_(hashes),
            Review.bucket.is_not(None),
            Review.theme.is_not(None),
            Review.severity.is_not(None),
            Run.quarantine_rate < 0.2,
        )
        .order_by(desc(Review.created_at))
    ).scalars()
    result: Dict[str, Review] = {}
    for row in rows:
        result.setdefault(row.review_hash, row)
    return result


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


def get_run_logs(session: Session, run_id: str) -> List[RunLog]:
    return list(session.execute(select(RunLog).where(RunLog.run_id == run_id).order_by(RunLog.created_at)).scalars())
