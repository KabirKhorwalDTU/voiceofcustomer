import asyncio
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy import delete, desc, select

from app.config import get_config
from app.db import session_scope
from app.models import Review, Run, RunLog, Theme
from app.pipeline.apify import BudgetExceeded, scrape_sources
from app.pipeline.cleaner import clean_and_dedup
from app.pipeline.gateway import BATCH_POLL_TIMEOUT_SECONDS, LLMGateway, redact_llm_error
from app.pipeline.synth import build_theme_rows
from app.pipeline.types import CleanReview, MAX_L2_THEMES, Tag, ThemeSet
from app.repository import get_settings, log_run_event, set_run_status


STALE_ACTIVE_RUN_AFTER = timedelta(minutes=30)
STALE_RECOVERY_CHECK_SECONDS = 60


def is_analysis_candidate(review: CleanReview) -> bool:
    if review.source == "reddit":
        return True
    return review.rating in {1, 2, 3}


def other_share_from_tags(tags: List[Tag]) -> float:
    if not tags:
        return 0
    return sum(1 for tag in tags if tag.theme == "other") / len(tags)


def enforce_l2_threshold(tags: List[Tag], theme_set: ThemeSet, min_parent_rows: int = 5) -> None:
    counts = Counter(tag.theme for tag in tags)
    for tag in tags:
        if counts[tag.theme] < min_parent_rows:
            tag.l2_theme = None
            continue
        allowed = theme_set.get(tag.theme, [])[:MAX_L2_THEMES]
        if tag.l2_theme not in allowed:
            tag.l2_theme = allowed[0] if allowed else None


def clear_run_outputs(session, run: Run) -> None:
    session.execute(delete(Theme).where(Theme.run_id == run.id))
    session.execute(delete(Review).where(Review.run_id == run.id))
    run.source_counts = {}
    run.completeness = {}
    run.cost_estimate = 0
    run.dedup_ratio = 0
    run.quarantine_rate = 0


def recover_stale_active_runs(session, now: Optional[datetime] = None, stale_after: timedelta = STALE_ACTIVE_RUN_AFTER) -> int:
    now = now or datetime.now(timezone.utc)
    cutoff = now - stale_after
    recovered = 0
    active_runs = list(
        session.execute(
            select(Run).where(Run.status.in_(("queued", "scraping", "classifying"))).order_by(Run.created_at)
        ).scalars()
    )
    for run in active_runs:
        latest_log = session.execute(
            select(RunLog).where(RunLog.run_id == run.id).order_by(desc(RunLog.created_at)).limit(1)
        ).scalars().first()
        last_seen = latest_log.created_at if latest_log else run.started_at or run.created_at
        if last_seen is None or last_seen > cutoff:
            continue
        prior_status = run.status
        clear_run_outputs(session, run)
        run.status = "queued"
        run.started_at = None
        run.finished_at = None
        run.error = None
        log_run_event(
            session,
            run,
            stage="ops",
            event="stale_active_run_requeued",
            status="warning",
            details={
                "prior_status": prior_status,
                "stale_after_minutes": int(stale_after.total_seconds() // 60),
                "last_seen_at": last_seen.isoformat() if last_seen else None,
                "last_event": latest_log.event if latest_log else None,
                "last_stage": latest_log.stage if latest_log else None,
                "reason": "active run had no fresh logs; assuming worker/deploy interruption and restarting full run",
            },
        )
        recovered += 1
    session.flush()
    return recovered


class Worker:
    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._last_recovery_check = 0.0

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task

    async def loop(self) -> None:
        while not self._stop.is_set():
            await self.recover_stale_runs_if_needed()
            run_id = self.next_run_id()
            if run_id:
                await self.process(run_id)
            else:
                await asyncio.sleep(1.5)

    async def recover_stale_runs_if_needed(self) -> None:
        loop = asyncio.get_running_loop()
        now = loop.time()
        if now - self._last_recovery_check < STALE_RECOVERY_CHECK_SECONDS:
            return
        self._last_recovery_check = now
        with session_scope() as session:
            recover_stale_active_runs(session)

    def next_run_id(self) -> Optional[str]:
        with session_scope() as session:
            run = session.execute(select(Run).where(Run.status == "queued").order_by(Run.created_at).limit(1)).scalars().first()
            return run.id if run else None

    async def process(self, run_id: str) -> None:
        config = get_config()
        try:
            with session_scope() as session:
                run = session.get(Run, run_id)
                if run is None:
                    return
                settings = get_settings(session)
                company = run.company
                clear_run_outputs(session, run)
                run.started_at = None
                run.finished_at = None
                set_run_status(session, run, "scraping")
                run.budget_cap = float(settings.per_run_budget_usd)
                run.model_used = f"{settings.provider}:{settings.model}"
                log_run_event(
                    session,
                    run,
                    stage="scraping",
                    event="stage_started",
                    status="ok",
                    provider="apify",
                    details={"max_reviews": settings.max_reviews, "budget_cap": float(settings.per_run_budget_usd)},
                )

            try:
                raw_reviews, completeness, source_counts, cost = await scrape_sources(company, settings, config, 0)
            except BudgetExceeded as exc:
                with session_scope() as session:
                    run = session.get(Run, run_id)
                    if run:
                        log_run_event(
                            session,
                            run,
                            stage="scraping",
                            event="budget_exceeded",
                            status="partial",
                            provider="ingestion",
                            cost_usd=float(settings.per_run_budget_usd),
                            details={"error": str(exc)},
                        )
                        run.completeness = {"budget": {"status": "aborted", "error": str(exc)}}
                        run.cost_estimate = float(settings.per_run_budget_usd)
                        set_run_status(session, run, "partial", str(exc))
                return

            with session_scope() as session:
                run = session.get(Run, run_id)
                if run is None:
                    return
                for source, status in completeness.items():
                    for attempt in status.get("attempt_details", []):
                        log_run_event(
                            session,
                            run,
                            stage="scraping",
                            event="source_attempt",
                            status=attempt.get("status", status.get("status", "info")),
                            source=source,
                            provider=attempt.get("provider", status.get("provider", "ingestion")),
                            attempt=attempt.get("attempt"),
                            cost_usd=float(attempt.get("cost_usd") or 0),
                            details={
                                "actor": status.get("actor"),
                                "library": status.get("library"),
                                "count": attempt.get("count", 0),
                                "error": attempt.get("error"),
                            },
                        )
                    log_run_event(
                        session,
                        run,
                        stage="scraping",
                        event="source_completed",
                        status=status.get("status", "info"),
                        source=source,
                        provider=status.get("provider", "ingestion"),
                        cost_usd=float(status.get("cost_usd") or 0),
                        details={
                            "actor": status.get("actor"),
                            "library": status.get("library"),
                            "attempts": status.get("attempts"),
                            "count": status.get("count"),
                            "error": status.get("error"),
                            "reason": status.get("reason"),
                            "places": status.get("places"),
                            "placeQueries": status.get("placeQueries"),
                            "searchTerms": status.get("searchTerms"),
                        },
                    )
                log_run_event(
                    session,
                    run,
                    stage="scraping",
                    event="stage_completed",
                    status="ok",
                    provider="apify",
                    cost_usd=float(cost),
                    details={"source_counts": source_counts, "raw_reviews": len(raw_reviews)},
                )

            cleaned_all, dedup_ratio = clean_and_dedup(raw_reviews, float(settings.dedup_threshold))
            cleaned = [review for review in cleaned_all if is_analysis_candidate(review)]
            selected_source_counts: Dict[str, int] = {}
            for review in cleaned:
                selected_source_counts[review.source] = selected_source_counts.get(review.source, 0) + 1
            for source in source_counts:
                selected_source_counts.setdefault(source, 0)
            with session_scope() as session:
                run = session.get(Run, run_id)
                if run is None:
                    return
                log_run_event(
                    session,
                    run,
                    stage="cleaning",
                    event="dedup_completed",
                    status="ok",
                    details={
                        "raw_reviews": len(raw_reviews),
                        "cleaned_before_rating_filter": len(cleaned_all),
                        "cleaned_reviews": len(cleaned),
                        "selected_reviews": len(cleaned),
                        "selection_rule": "rating_1_2_3_for_rated_sources_plus_reddit_when_enabled",
                        "raw_source_counts": source_counts,
                        "selected_source_counts": selected_source_counts,
                        "dedup_ratio": dedup_ratio,
                        "dedup_threshold": float(settings.dedup_threshold),
                    },
                )

            if not cleaned:
                with session_scope() as session:
                    run = session.get(Run, run_id)
                    if run is None:
                        return
                    run.completeness = completeness
                    run.source_counts = selected_source_counts
                    run.cost_estimate = cost
                    run.dedup_ratio = dedup_ratio
                    run.quarantine_rate = 0
                    log_run_event(
                        session,
                        run,
                        stage="terminal",
                        event="run_completed",
                        status="partial",
                        details={"reason": "No 1/2/3-star analysis reviews were selected; source completeness contains per-source details."},
                    )
                    set_run_status(session, run, "partial", "No 1/2/3-star analysis reviews were selected; source completeness contains per-source details.")
                return

            with session_scope() as session:
                run = session.get(Run, run_id)
                if run is None:
                    return
                run.completeness = completeness
                run.source_counts = selected_source_counts
                run.cost_estimate = cost
                run.dedup_ratio = dedup_ratio
                set_run_status(session, run, "classifying")

                review_rows: Dict[str, Review] = {}
                for review in cleaned:
                    if review.review_hash in review_rows:
                        continue
                    row = Review(
                        run_id=run.id,
                        company_id=run.company_id,
                        review_hash=review.review_hash,
                        source=review.source,
                        date=review.date,
                        rating=review.rating,
                        text=review.text,
                        language=review.language,
                        theme=None,
                        l2_theme=None,
                    )
                    session.add(row)
                    review_rows[review.review_hash] = row
                session.flush()
                log_run_event(
                    session,
                    run,
                    stage="classification",
                    event="complete_rerun_prepared",
                    status="ok",
                    details={
                        "cleaned_reviews": len(cleaned),
                        "classified_reviews": len(cleaned),
                        "reused_reviews": 0,
                        "reason": "incremental tag reuse disabled; every run is a full reclassification",
                    },
                )

            def make_llm_progress_logger(stage: str):
                async def log_llm_progress(event: Dict[str, object]) -> None:
                    with session_scope() as progress_session:
                        progress_run = progress_session.get(Run, run_id)
                        if progress_run:
                            log_run_event(
                                progress_session,
                                progress_run,
                                stage=stage,
                                event="llm_batch_progress",
                                status="info",
                                provider=settings.provider,
                                model=settings.model,
                                details=event,
                            )

                return log_llm_progress

            gateway = LLMGateway(config, settings, progress_callback=make_llm_progress_logger("classification"))
            with session_scope() as session:
                run = session.get(Run, run_id)
                if run is None:
                    return
                log_run_event(
                    session,
                    run,
                    stage="theme_discovery",
                    event="stage_started",
                    status="ok",
                        provider=settings.provider,
                        model=settings.model,
                    details={"review_count": len(cleaned), "sampling": "all_selected_reviews"},
                )
            theme_set = await gateway.discover_themes(cleaned)
            with session_scope() as session:
                run = session.get(Run, run_id)
                if run is None:
                    return
                log_run_event(
                    session,
                    run,
                    stage="theme_discovery",
                    event="stage_completed",
                    status="ok",
                    provider=settings.provider,
                    model=settings.model,
                    details={"theme_set": theme_set},
                )
                log_run_event(
                    session,
                    run,
                    stage="classification",
                    event="stage_started",
                    status="ok",
                    provider=settings.provider,
                    model=settings.model,
                    details={"classified_reviews": len(cleaned), "batch_size": settings.batch_size, "theme_count": len(theme_set)},
                )
            if settings.provider == "gemini":
                classification_timeout = BATCH_POLL_TIMEOUT_SECONDS + 600
            else:
                classification_timeout = max(3600, ((len(cleaned) + int(settings.batch_size) - 1) // int(settings.batch_size)) * 120)
            try:
                tags, usage = await asyncio.wait_for(gateway.classify_all(cleaned, theme_set), timeout=classification_timeout)
            except asyncio.TimeoutError:
                usage = gateway.usage
                total_batches = (len(cleaned) + int(settings.batch_size) - 1) // int(settings.batch_size)
                usage.path = f"{usage.path}_timeout_heuristic_fallback"
                usage.total_batches = total_batches
                usage.quarantined_batches = total_batches
                usage.malformed_retries.append(
                    {
                        "attempt": "classification_timeout",
                        "reason": f"classification exceeded {classification_timeout}s and fell back to quarantined heuristic tags",
                    }
                )
                tags = [gateway._heuristic_tag(review, theme_set, quarantine=True) for review in cleaned]

            other_share_before_repair = other_share_from_tags(tags)
            other_share_after_repair = other_share_before_repair
            if other_share_before_repair > 0.15:
                other_hashes = {tag.review_hash for tag in tags if tag.theme == "other"}
                other_reviews = [review for review in cleaned if review.review_hash in other_hashes]
                with session_scope() as session:
                    run = session.get(Run, run_id)
                    if run:
                        log_run_event(
                            session,
                            run,
                            stage="classification",
                            event="other_share_repair_started",
                            status="warning",
                            provider=settings.provider,
                            model=settings.model,
                            details={"other_share": round(other_share_before_repair, 4), "other_reviews": len(other_reviews), "target_other_share": 0.15},
                        )
                repaired_theme_set = await gateway.repair_theme_set(other_reviews, theme_set)
                try:
                    repair_tags, usage = await asyncio.wait_for(gateway.classify_all(other_reviews, repaired_theme_set), timeout=classification_timeout)
                    repair_map = {tag.review_hash: tag for tag in repair_tags}
                    tags = [repair_map.get(tag.review_hash, tag) if tag.theme == "other" else tag for tag in tags]
                    theme_set = repaired_theme_set
                    other_share_after_repair = other_share_from_tags(tags)
                except (asyncio.TimeoutError, RuntimeError) as exc:
                    usage = gateway.usage
                    usage.malformed_retries.append({"attempt": "other_repair_failed", "reason": redact_llm_error(exc)})
                with session_scope() as session:
                    run = session.get(Run, run_id)
                    if run:
                        log_run_event(
                            session,
                            run,
                            stage="classification",
                            event="other_share_repair_completed",
                            status="ok" if other_share_after_repair <= 0.15 else "warning",
                            provider=settings.provider,
                            model=settings.model,
                            details={
                                "other_share_before": round(other_share_before_repair, 4),
                                "other_share_after": round(other_share_after_repair, 4),
                                "theme_count": len(theme_set),
                            },
                        )
            enforce_l2_threshold(tags, theme_set, min_parent_rows=5)
            tag_map: Dict[str, Tag] = {tag.review_hash: tag for tag in tags}

            with session_scope() as session:
                run = session.get(Run, run_id)
                if run is None:
                    return
                rows = list(session.execute(select(Review).where(Review.run_id == run.id)).scalars())
                for row in rows:
                    tag = tag_map.get(row.review_hash)
                    if tag:
                        row.theme = tag.theme if tag.theme in theme_set else "other"
                        row.l2_theme = tag.l2_theme if row.theme in theme_set else "other"

                run.cost_estimate = round(float(run.cost_estimate or 0) + usage.cost_usd, 4)
                run.quarantine_rate = min(1, usage.quarantined_batches / usage.total_batches) if usage.total_batches else 0
                log_run_event(
                    session,
                    run,
                    stage="classification",
                    event="stage_completed",
                    status="ok" if usage.quarantined_batches == 0 else "partial",
                    provider=settings.provider,
                    model=settings.model,
                    cost_usd=usage.cost_usd,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    total_tokens=usage.total_tokens,
                    details={
                        "calls": usage.calls,
                        "path": usage.path,
                        "batch_probe": usage.batch_probe,
                        "total_batches": usage.total_batches,
                        "quarantined_batches": usage.quarantined_batches,
                        "malformed_retries": usage.malformed_retries,
                        "progress_events": usage.progress_events[-50:],
                        "tagged_reviews": len(tags),
                        "other_share_before_repair": round(other_share_before_repair, 4),
                        "other_share_after_repair": round(other_share_after_repair, 4),
                        "l2_min_parent_reviews": 5,
                    },
                )

                if run.cost_estimate > float(settings.per_run_budget_usd):
                    log_run_event(
                        session,
                        run,
                        stage="budget",
                        event="budget_exceeded",
                        status="partial",
                        cost_usd=float(run.cost_estimate),
                        details={"budget_cap": float(settings.per_run_budget_usd)},
                    )
                    set_run_status(session, run, "partial", "Budget cap exceeded after LLM processing")

                session.execute(delete(Theme).where(Theme.run_id == run.id))
                session.flush()
                rows = list(session.execute(select(Review).where(Review.run_id == run.id)).scalars())
                theme_rows = build_theme_rows(run, rows, settings.source_weights, settings.recency_window_days)
                top_hashes = {
                    quote.get("text")
                    for theme in theme_rows
                    for quote in (theme.top_quotes or [])
                }
                for row in rows:
                    row.representative_flag = row.text in top_hashes
                session.add_all(theme_rows)
                log_run_event(
                    session,
                    run,
                    stage="synthesis",
                    event="themes_built",
                    status="ok",
                    details={"theme_count": len(theme_rows), "representative_quotes": len(top_hashes)},
                )

                failed_sources = [src for src, status in (run.completeness or {}).items() if status.get("status") not in {"ok", "disabled"}]
                terminal = "partial" if failed_sources or run.status == "partial" else "done"
                log_run_event(
                    session,
                    run,
                    stage="terminal",
                    event="run_completed",
                    status=terminal,
                    cost_usd=float(run.cost_estimate or 0),
                    details={
                        "failed_sources": failed_sources,
                        "source_counts": run.source_counts,
                        "dedup_ratio": run.dedup_ratio,
                        "quarantine_rate": run.quarantine_rate,
                    },
                )
                set_run_status(session, run, terminal)
        except Exception as exc:
            with session_scope() as session:
                run = session.get(Run, run_id)
                if run:
                    error = redact_llm_error(exc)
                    log_run_event(session, run, stage="terminal", event="run_failed", status="failed", details={"error": error})
                    set_run_status(session, run, "failed", error)


worker = Worker()
