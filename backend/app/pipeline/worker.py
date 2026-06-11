import asyncio
from typing import Dict, List, Optional

from sqlalchemy import delete, select

from app.config import get_config
from app.db import session_scope
from app.models import Review, Run, Theme
from app.pipeline.apify import BudgetExceeded, scrape_sources
from app.pipeline.cleaner import clean_and_dedup
from app.pipeline.gateway import LLMGateway, redact_llm_error
from app.pipeline.synth import build_theme_rows
from app.pipeline.types import CleanReview, Tag
from app.repository import get_settings, log_run_event, prior_tags_by_hash, set_run_status


def stratified_sample(reviews: List[CleanReview], limit: int = 300) -> List[CleanReview]:
    buckets: Dict[str, List[CleanReview]] = {}
    for review in reviews:
        key = f"{review.source}:{review.rating or 'none'}"
        buckets.setdefault(key, []).append(review)
    sample: List[CleanReview] = []
    while buckets and len(sample) < limit:
        for key in list(buckets.keys()):
            values = buckets[key]
            if values:
                sample.append(values.pop(0))
                if len(sample) >= limit:
                    break
            if not values:
                buckets.pop(key, None)
    return sample


class Worker:
    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task

    async def loop(self) -> None:
        while not self._stop.is_set():
            run_id = self.next_run_id()
            if run_id:
                await self.process(run_id)
            else:
                await asyncio.sleep(1.5)

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
                            provider=status.get("provider", "ingestion"),
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

            cleaned, dedup_ratio = clean_and_dedup(raw_reviews, float(settings.dedup_threshold))
            hashes = [review.review_hash for review in cleaned]
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
                        "cleaned_reviews": len(cleaned),
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
                    run.source_counts = source_counts
                    run.cost_estimate = cost
                    run.dedup_ratio = dedup_ratio
                    run.quarantine_rate = 0
                    log_run_event(
                        session,
                        run,
                        stage="terminal",
                        event="run_completed",
                        status="partial",
                        details={"reason": "No reviews were ingested; source completeness contains per-source details."},
                    )
                    set_run_status(session, run, "partial", "No reviews were ingested; source completeness contains per-source details.")
                return

            with session_scope() as session:
                run = session.get(Run, run_id)
                if run is None:
                    return
                run.completeness = completeness
                run.source_counts = source_counts
                run.cost_estimate = cost
                run.dedup_ratio = dedup_ratio
                set_run_status(session, run, "classifying")

                prior = prior_tags_by_hash(session, run.company_id, hashes)
                review_rows: Dict[str, Review] = {}
                new_reviews: List[CleanReview] = []
                for review in cleaned:
                    if review.review_hash in review_rows:
                        continue
                    reused = prior.get(review.review_hash)
                    row = Review(
                        run_id=run.id,
                        company_id=run.company_id,
                        review_hash=review.review_hash,
                        source=review.source,
                        date=review.date,
                        rating=review.rating,
                        text=review.text,
                        language=reused.language if reused else review.language,
                        english_gloss=reused.english_gloss if reused else None,
                        bucket=reused.bucket if reused else None,
                        theme=reused.theme if reused else None,
                        severity=reused.severity if reused else None,
                    )
                    session.add(row)
                    review_rows[review.review_hash] = row
                    if reused is None:
                        new_reviews.append(review)
                session.flush()
                log_run_event(
                    session,
                    run,
                    stage="classification",
                    event="incremental_reuse_checked",
                    status="ok",
                    details={
                        "cleaned_reviews": len(cleaned),
                        "reused_reviews": len(cleaned) - len(new_reviews),
                        "new_reviews": len(new_reviews),
                    },
                )

            async def log_llm_progress(event: Dict[str, object]) -> None:
                with session_scope() as progress_session:
                    progress_run = progress_session.get(Run, run_id)
                    if progress_run:
                        log_run_event(
                            progress_session,
                            progress_run,
                            stage="classification",
                            event="llm_batch_progress",
                            status="info",
                            provider=settings.provider,
                            model=settings.model,
                            details=event,
                        )

            gateway = LLMGateway(config, settings, progress_callback=log_llm_progress)
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
                    details={"sample_size": len(stratified_sample(cleaned))},
                )
            theme_set = await gateway.discover_themes(stratified_sample(cleaned))
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
                    details={"new_reviews": len(new_reviews), "batch_size": settings.batch_size},
                )
            classification_timeout = max(3600, ((len(new_reviews) + int(settings.batch_size) - 1) // int(settings.batch_size)) * 120)
            try:
                tags, usage = await asyncio.wait_for(gateway.classify_all(new_reviews, theme_set), timeout=classification_timeout)
            except asyncio.TimeoutError:
                usage = gateway.usage
                total_batches = (len(new_reviews) + int(settings.batch_size) - 1) // int(settings.batch_size)
                usage.path = f"{usage.path}_timeout_heuristic_fallback"
                usage.total_batches = total_batches
                usage.quarantined_batches = total_batches
                usage.malformed_retries.append(
                    {
                        "attempt": "classification_timeout",
                        "reason": f"classification exceeded {classification_timeout}s and fell back to quarantined heuristic tags",
                    }
                )
                tags = [gateway._heuristic_tag(review, theme_set, quarantine=True) for review in new_reviews]
            tag_map: Dict[str, Tag] = {tag.review_hash: tag for tag in tags}

            with session_scope() as session:
                run = session.get(Run, run_id)
                if run is None:
                    return
                rows = list(session.execute(select(Review).where(Review.run_id == run.id)).scalars())
                for row in rows:
                    tag = tag_map.get(row.review_hash)
                    if tag:
                        row.language = tag.language
                        row.english_gloss = tag.english_gloss
                        row.bucket = tag.bucket
                        row.theme = tag.theme if tag.theme in theme_set.get(tag.bucket, []) else "other"
                        row.severity = tag.severity
                    elif row.bucket and row.theme and row.theme not in theme_set.get(row.bucket, []):
                        row.theme = "other"

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
