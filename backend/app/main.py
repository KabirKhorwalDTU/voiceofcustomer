import asyncio
from collections import defaultdict
from datetime import date, datetime, timezone
import logging
import math
import os
import time
from typing import Dict, List, Tuple

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app.auth import Actor, clean_guest_id, create_or_get_user, create_user_session, resolve_actor
from app.config import get_config
from app.db import init_db, session_scope
from app.models import User
from app.onboarding import normalize_business_type, recommended_sources, source_catalog
from app.pipeline.resolver import resolve_links
from app.pipeline.synth import build_deck_spec, build_report_snapshot, build_summary, export_reviews
from app.pipeline.worker import worker
from app.repository import (
    can_access_run,
    claim_guest_workspace,
    grant_legacy_kabir_workspace,
    create_run,
    delete_run_by_id,
    get_company_runs,
    get_latest_run_log,
    get_latest_run_logs,
    get_actor_run_statuses,
    get_egress_usage,
    get_run_cost_rollup,
    get_run,
    get_run_logs,
    get_run_results,
    get_settings,
    is_legacy_workspace_actor,
    list_visible_runs_page,
    persist_api_usage,
    query_run_reviews,
    rerun_company_from_run,
    update_settings,
)
from app.schemas import (
    AuthLoginRequest,
    AuthLoginResponse,
    CompanyDiscoveryOut,
    CompanyDiscoveryRequest,
    ResultsOut,
    EgressOpsOut,
    ReviewPageOut,
    RunLogOut,
    RunOut,
    RunListItemOut,
    RunPageOut,
    RunStatusOut,
    RunStatusPageOut,
    SettingsOut,
    SettingsUpdate,
    SubmitRunRequest,
    SubmitRunResponse,
    UserOut,
)


_LATEST_LOG_NOT_PROVIDED = object()
logger = logging.getLogger(__name__)


class ApiUsageMeter:
    """Batches response-body measurements so telemetry itself stays inexpensive."""

    def __init__(self, cycle_day: int, flush_seconds: int = 60) -> None:
        self.cycle_day = max(1, min(cycle_day, 28))
        self.flush_seconds = max(15, flush_seconds)
        self._pending: Dict[Tuple[date, str, int], List[int]] = defaultdict(lambda: [0, 0])
        # Persist the first observed request, then batch future updates. This
        # avoids an idle process losing all telemetry before the first minute.
        self._last_flush = 0.0
        self._flush_lock = asyncio.Lock()

    def record(self, endpoint: str, status_code: int, response_bytes: int) -> None:
        key = (datetime.now(timezone.utc).date(), endpoint, int(status_code))
        bucket = self._pending[key]
        bucket[0] += 1
        bucket[1] += max(0, int(response_bytes))

    async def flush_if_due(self) -> None:
        if time.monotonic() - self._last_flush >= self.flush_seconds:
            await self.flush()

    async def flush(self, force: bool = False) -> None:
        async with self._flush_lock:
            if not force and time.monotonic() - self._last_flush < self.flush_seconds:
                return
            pending = {key: (value[0], value[1]) for key, value in self._pending.items()}
            self._pending.clear()
            self._last_flush = time.monotonic()
        if not pending:
            return
        try:
            warnings = await asyncio.to_thread(self._persist, pending)
        except Exception:
            logger.exception("Failed to persist API egress metrics")
            async with self._flush_lock:
                for key, value in pending.items():
                    bucket = self._pending[key]
                    bucket[0] += value[0]
                    bucket[1] += value[1]
            return
        for warning in warnings:
            logger.warning(
                "Estimated Supabase response egress crossed %.1f GB for cycle %s (%s bytes)",
                warning.threshold_bytes / 1_000_000_000,
                warning.cycle_start.isoformat(),
                warning.estimated_bytes,
            )

    def _persist(self, pending: Dict[Tuple[date, str, int], Tuple[int, int]]):
        with session_scope() as session:
            return persist_api_usage(session, pending, cycle_day=self.cycle_day)


class ApiUsageMetricsMiddleware:
    def __init__(self, app, meter: ApiUsageMeter) -> None:
        self.app = app
        self.meter = meter

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        status_code = 500
        response_bytes = 0

        async def measured_send(message):
            nonlocal status_code, response_bytes
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            elif message["type"] == "http.response.body":
                response_bytes += len(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive, measured_send)
        finally:
            path = scope.get("path", "")
            if path.startswith("/api/"):
                route = scope.get("route")
                endpoint = getattr(route, "path", path)
                self.meter.record(endpoint, status_code, response_bytes)
                await self.meter.flush_if_due()


app = FastAPI(title="Voice of Customer AI Agent", version="1.0.0")
config = get_config()
egress_cycle_day = int(os.getenv("SUPABASE_EGRESS_CYCLE_DAY", "24"))
api_usage_meter = ApiUsageMeter(egress_cycle_day)
app.add_middleware(ApiUsageMetricsMiddleware, meter=api_usage_meter)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """Keep unexpected API failures readable to a browser client without leaking internals."""
    logger.exception("Unhandled API error", exc_info=exc)
    response = JSONResponse(status_code=500, content={"detail": "The analysis service hit a temporary error. Please try again."})
    origin = request.headers.get("origin", "")
    if origin in config.cors_origins:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Vary"] = "Origin"
    return response


@app.on_event("startup")
async def startup() -> None:
    app.state.bootstrap_ready = False
    app.state.bootstrap_error = ""
    app.state.bootstrap_task = asyncio.create_task(bootstrap_backend())
    app.state.usage_metrics_task = asyncio.create_task(flush_usage_metrics_forever())


@app.on_event("shutdown")
async def shutdown() -> None:
    task = getattr(app.state, "bootstrap_task", None)
    if task and not task.done():
        task.cancel()
    metrics_task = getattr(app.state, "usage_metrics_task", None)
    if metrics_task and not metrics_task.done():
        metrics_task.cancel()
        try:
            await metrics_task
        except asyncio.CancelledError:
            pass
    await api_usage_meter.flush(force=True)
    await worker.stop()


@app.get("/health")
def health() -> dict:
    return {"ok": True, "bootstrap_ready": bool(getattr(app.state, "bootstrap_ready", False))}


def header_actor(session, authorization: str, x_guest_id: str, x_operator_mode: str) -> Actor:
    actor = resolve_actor(session, authorization=authorization, guest_id=x_guest_id, operator_mode=x_operator_mode)
    # The former /kabir route could set this header from any browser. Operator
    # endpoints now require an authenticated Kabir session, never a client flag.
    if actor.is_operator and not is_legacy_workspace_actor(session, actor):
        actor.is_operator = False
    return actor


async def bootstrap_backend() -> None:
    for attempt in range(1, 13):
        try:
            await asyncio.to_thread(init_db)
            worker.start()
            app.state.bootstrap_ready = True
            app.state.bootstrap_error = ""
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            app.state.bootstrap_error = exc.__class__.__name__
            logger.warning("Backend bootstrap attempt %s failed with %s", attempt, exc.__class__.__name__)
            await asyncio.sleep(min(30, attempt * 5))
    logger.error("Backend bootstrap failed after all retry attempts.")


async def flush_usage_metrics_forever() -> None:
    """Persist endpoint byte counters even if the next request never arrives."""
    while True:
        await asyncio.sleep(api_usage_meter.flush_seconds)
        await api_usage_meter.flush(force=True)


@app.post("/api/auth/login", response_model=AuthLoginResponse)
def login(request: AuthLoginRequest) -> AuthLoginResponse:
    with session_scope() as session:
        user = create_or_get_user(session, request.email)
        claimed_runs = claim_guest_workspace(session, clean_guest_id(request.guest_id), user.id)
        claimed_runs += grant_legacy_kabir_workspace(session, user.id)
        token, _ = create_user_session(session, user)
        return AuthLoginResponse(user=UserOut.model_validate(user), token=token, claimed_runs=claimed_runs)


@app.get("/api/auth/me", response_model=UserOut)
def me(
    authorization: str = Header(default=""),
    x_guest_id: str = Header(default=""),
    x_operator_mode: str = Header(default=""),
) -> UserOut:
    with session_scope() as session:
        actor = header_actor(session, authorization, x_guest_id, x_operator_mode)
        if not actor.user_id:
            raise HTTPException(status_code=401, detail="not signed in")
        user = session.get(User, actor.user_id)
        if user is None:
            raise HTTPException(status_code=401, detail="not signed in")
        return UserOut.model_validate(user)


@app.post("/api/onboarding/discover", response_model=CompanyDiscoveryOut)
def discover_company(request: CompanyDiscoveryRequest) -> CompanyDiscoveryOut:
    """Resolve cheap public identifiers before asking a small business for more links."""
    resolved = resolve_links("", "", request.website, request.name)
    business_type = normalize_business_type(request.business_type)
    if business_type == "other" and (resolved.play_id or resolved.app_id):
        business_type = "app"
    display_name = request.name.strip()
    icon_text = "".join(part[:1] for part in display_name.split()[:2]).upper() or "VO"
    return CompanyDiscoveryOut(
        name=display_name,
        domain=resolved.domain,
        brand_keyword=resolved.brand_keyword,
        play_id=resolved.play_id,
        app_id=resolved.app_id,
        icon_text=icon_text,
        business_type=business_type,
        recommended_sources=recommended_sources(business_type),
        source_catalog=source_catalog(),
    )


@app.post("/api/runs", response_model=SubmitRunResponse)
def submit_run(
    request: SubmitRunRequest,
    authorization: str = Header(default=""),
    x_guest_id: str = Header(default=""),
    x_operator_mode: str = Header(default=""),
) -> SubmitRunResponse:
    with session_scope() as session:
        actor = header_actor(session, authorization, x_guest_id, x_operator_mode)
        if not (actor.is_operator or actor.user_id or actor.guest_id):
            raise HTTPException(status_code=401, detail="guest or signed-in session required")
        run, existing = create_run(session, request, actor)
        session.flush()
        return SubmitRunResponse(run=run_out(session, run), deduped_existing=existing)


@app.get("/api/runs", response_model=RunPageOut)
def runs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=50),
    q: str = Query(default="", max_length=160),
    authorization: str = Header(default=""),
    x_guest_id: str = Header(default=""),
    x_operator_mode: str = Header(default=""),
) -> RunPageOut:
    with session_scope() as session:
        actor = header_actor(session, authorization, x_guest_id, x_operator_mode)
        if not (actor.is_operator or actor.user_id or actor.guest_id):
            return RunPageOut(items=[], total=0, page=page, page_size=page_size, pages=1)
        run_rows, total = list_visible_runs_page(session, actor, page=page, page_size=page_size, query=q)
        latest_logs = get_latest_run_logs(session, [run.id for run in run_rows])
        return RunPageOut(
            items=[run_list_item_out(session, run, latest_logs.get(run.id)) for run in run_rows],
            total=total,
            page=page,
            page_size=page_size,
            pages=max(1, math.ceil(total / page_size)),
        )


@app.get("/api/runs/status", response_model=RunStatusPageOut)
def run_statuses(
    ids: str = Query(min_length=1, max_length=1000),
    authorization: str = Header(default=""),
    x_guest_id: str = Header(default=""),
    x_operator_mode: str = Header(default=""),
) -> RunStatusPageOut:
    requested_ids = list(dict.fromkeys(value.strip() for value in ids.split(",") if value.strip()))
    if not requested_ids or len(requested_ids) > 20:
        raise HTTPException(status_code=400, detail="provide between 1 and 20 run ids")
    with session_scope() as session:
        actor = header_actor(session, authorization, x_guest_id, x_operator_mode)
        if not (actor.is_operator or actor.user_id or actor.guest_id):
            raise HTTPException(status_code=401, detail="guest or signed-in session required")
        rows = get_actor_run_statuses(session, actor, requested_ids)
        latest_logs = get_latest_run_logs(session, [run.id for run in rows])
        return RunStatusPageOut(items=[run_status_out(session, run, latest_logs.get(run.id)) for run in rows])


@app.get("/api/runs/{run_id}", response_model=RunOut)
def run_status(
    run_id: str,
    authorization: str = Header(default=""),
    x_guest_id: str = Header(default=""),
    x_operator_mode: str = Header(default=""),
) -> RunOut:
    with session_scope() as session:
        actor = header_actor(session, authorization, x_guest_id, x_operator_mode)
        run = get_run(session, run_id)
        if not run or not can_access_run(run, actor, session):
            raise HTTPException(status_code=404, detail="run not found")
        return run_out(session, run)


@app.post("/api/runs/{run_id}/rerun", response_model=SubmitRunResponse)
def rerun(
    run_id: str,
    authorization: str = Header(default=""),
    x_guest_id: str = Header(default=""),
    x_operator_mode: str = Header(default=""),
) -> SubmitRunResponse:
    with session_scope() as session:
        actor = header_actor(session, authorization, x_guest_id, x_operator_mode)
        try:
            run, existing = rerun_company_from_run(session, run_id, actor)
        except KeyError:
            raise HTTPException(status_code=404, detail="run not found") from None
        session.flush()
        return SubmitRunResponse(run=run_out(session, run), deduped_existing=existing)


@app.delete("/api/runs/{run_id}", status_code=204)
def delete_run(
    run_id: str,
    authorization: str = Header(default=""),
    x_guest_id: str = Header(default=""),
    x_operator_mode: str = Header(default=""),
) -> Response:
    with session_scope() as session:
        actor = header_actor(session, authorization, x_guest_id, x_operator_mode)
        try:
            deleted = delete_run_by_id(session, run_id, actor)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        if not deleted:
            raise HTTPException(status_code=404, detail="run not found")
    return Response(status_code=204)


@app.get("/api/companies/{company_id}/runs", response_model=List[RunOut])
def company_runs(
    company_id: str,
    authorization: str = Header(default=""),
    x_guest_id: str = Header(default=""),
    x_operator_mode: str = Header(default=""),
) -> List[RunOut]:
    with session_scope() as session:
        actor = header_actor(session, authorization, x_guest_id, x_operator_mode)
        run_rows = get_company_runs(session, company_id, actor)
        latest_logs = get_latest_run_logs(session, [run.id for run in run_rows])
        return [run_out(session, run, latest_logs.get(run.id)) for run in run_rows]


@app.get("/api/runs/{run_id}/results", response_model=ResultsOut)
def results(
    run_id: str,
    authorization: str = Header(default=""),
    x_guest_id: str = Header(default=""),
    x_operator_mode: str = Header(default=""),
) -> ResultsOut:
    with session_scope() as session:
        actor = header_actor(session, authorization, x_guest_id, x_operator_mode)
        run = get_run(session, run_id)
        if not run or not can_access_run(run, actor, session):
            raise HTTPException(status_code=404, detail="run not found") from None
        snapshot = get_or_create_report_snapshot(session, run, actor)
        if snapshot:
            summary = dict(snapshot.get("summary") or {})
            themes = list(snapshot.get("themes") or [])
            deck_spec = str(snapshot.get("deck_spec") or "")
        else:
            summary = {
                "total_reviews": 0,
                "source_mix": {},
                "rating_distribution": {},
                "source_quality": [],
                "top_themes": [],
                "other_share": 0,
                "low_confidence": False,
                "completeness": run.completeness or {},
                "cost_estimate": run.cost_estimate or 0,
                "quarantine_rate": run.quarantine_rate or 0,
                "insight_summary": run.insight_summary or {},
            }
            themes = []
            deck_spec = ""
        return ResultsOut(
            company=run.company,
            run=run_out(session, run),
            reviews=[],
            themes=themes,
            logs=[],
            summary=summary,
            deck_spec=deck_spec,
        )


@app.get("/api/runs/{run_id}/reviews", response_model=ReviewPageOut)
def run_reviews(
    run_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    source: str = "",
    theme: str = "",
    l2_theme: str = "",
    rating: str = "",
    review_hash: str = "",
    date_query: str = "",
    text_query: str = "",
    q: str = "",
    authorization: str = Header(default=""),
    x_guest_id: str = Header(default=""),
    x_operator_mode: str = Header(default=""),
) -> ReviewPageOut:
    with session_scope() as session:
        actor = header_actor(session, authorization, x_guest_id, x_operator_mode)
        try:
            rows, total = query_run_reviews(
                session,
                run_id,
                actor=actor,
                page=page,
                page_size=page_size,
                source=source,
                theme=theme,
                l2_theme=l2_theme,
                rating=rating,
                review_hash=review_hash,
                date_query=date_query,
                text_query=text_query,
                q=q,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="run not found") from None
        return ReviewPageOut(items=rows, total=total, page=page, page_size=page_size, pages=max(1, math.ceil(total / page_size)))


@app.get("/api/runs/{run_id}/logs", response_model=List[RunLogOut])
def run_logs(
    run_id: str,
    authorization: str = Header(default=""),
    x_guest_id: str = Header(default=""),
    x_operator_mode: str = Header(default=""),
) -> List[RunLogOut]:
    with session_scope() as session:
        actor = header_actor(session, authorization, x_guest_id, x_operator_mode)
        run = get_run(session, run_id)
        if not run or not can_access_run(run, actor, session):
            raise HTTPException(status_code=404, detail="run not found")
        return [RunLogOut.model_validate(row) for row in get_run_logs(session, run_id)]


@app.get("/api/runs/{run_id}/downloads/{fmt}")
def download(
    run_id: str,
    fmt: str,
    authorization: str = Header(default=""),
    x_guest_id: str = Header(default=""),
    x_operator_mode: str = Header(default=""),
) -> Response:
    with session_scope() as session:
        actor = header_actor(session, authorization, x_guest_id, x_operator_mode)
        try:
            _, _, reviews, _ = get_run_results(session, run_id, actor)
        except KeyError:
            raise HTTPException(status_code=404, detail="run not found") from None
        try:
            body, media_type, filename = export_reviews(reviews, fmt)
        except ValueError:
            raise HTTPException(status_code=400, detail="format must be xlsx, csv, or json") from None
        return Response(
            content=body,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )


@app.get("/api/runs/{run_id}/deck-spec.md")
def deck_spec(
    run_id: str,
    authorization: str = Header(default=""),
    x_guest_id: str = Header(default=""),
    x_operator_mode: str = Header(default=""),
) -> Response:
    with session_scope() as session:
        actor = header_actor(session, authorization, x_guest_id, x_operator_mode)
        run = get_run(session, run_id)
        if not run or not can_access_run(run, actor, session):
            raise HTTPException(status_code=404, detail="run not found") from None
        snapshot = get_or_create_report_snapshot(session, run, actor)
        if not snapshot:
            raise HTTPException(status_code=409, detail="report is still being prepared")
        return Response(str(snapshot.get("deck_spec") or ""), media_type="text/markdown")


@app.get("/api/settings", response_model=SettingsOut)
def read_settings(
    authorization: str = Header(default=""),
    x_guest_id: str = Header(default=""),
    x_operator_mode: str = Header(default=""),
) -> SettingsOut:
    with session_scope() as session:
        actor = header_actor(session, authorization, x_guest_id, x_operator_mode)
        if not actor.is_operator:
            raise HTTPException(status_code=403, detail="operator mode required")
        return SettingsOut.model_validate(get_settings(session))


@app.put("/api/settings", response_model=SettingsOut)
def write_settings(
    update: SettingsUpdate,
    authorization: str = Header(default=""),
    x_guest_id: str = Header(default=""),
    x_operator_mode: str = Header(default=""),
) -> SettingsOut:
    with session_scope() as session:
        actor = header_actor(session, authorization, x_guest_id, x_operator_mode)
        if not actor.is_operator:
            raise HTTPException(status_code=403, detail="operator mode required")
        settings = update_settings(session, update.model_dump(exclude_unset=True))
        return SettingsOut.model_validate(settings)


@app.get("/api/ops/egress", response_model=EgressOpsOut)
def egress_operations(
    authorization: str = Header(default=""),
    x_guest_id: str = Header(default=""),
    x_operator_mode: str = Header(default=""),
) -> EgressOpsOut:
    with session_scope() as session:
        actor = header_actor(session, authorization, x_guest_id, x_operator_mode)
        if not actor.is_operator:
            raise HTTPException(status_code=403, detail="operator mode required")
        cycle_start, cycle_end, total_bytes, entries, warnings = get_egress_usage(session, cycle_day=egress_cycle_day)
        return EgressOpsOut(
            cycle_start=cycle_start,
            cycle_end=cycle_end,
            estimated_response_bytes=total_bytes,
            estimated_response_gb=round(total_bytes / 1_000_000_000, 6),
            warning_thresholds_gb=[2.0, 3.5, 4.5],
            warnings=warnings,
            endpoints=entries,
        )


def run_out(session, run, latest_log=_LATEST_LOG_NOT_PROVIDED) -> RunOut:
    output = RunOut.model_validate(run)
    latest = get_latest_run_log(session, run.id) if latest_log is _LATEST_LOG_NOT_PROVIDED else latest_log
    stage = latest.stage if latest else run.status
    event = latest.event if latest else ""
    output.current_stage = stage_label(run.status, stage, event)
    output.stage_detail = event.replace("_", " ") if event else ""
    output.progress = stage_progress(run.status, stage)
    return output


def run_list_item_out(session, run, latest_log=_LATEST_LOG_NOT_PROVIDED) -> RunListItemOut:
    latest = get_latest_run_log(session, run.id) if latest_log is _LATEST_LOG_NOT_PROVIDED else latest_log
    stage = latest.stage if latest else run.status
    event = latest.event if latest else ""
    return RunListItemOut(
        id=run.id,
        company_id=run.company_id,
        status=run.status,
        model_used=run.model_used,
        cost_estimate=float(run.cost_estimate or 0),
        budget_cap=float(run.budget_cap or 0),
        quarantine_rate=float(run.quarantine_rate or 0),
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
        company=run.company,
        current_stage=stage_label(run.status, stage, event),
        stage_detail=event.replace("_", " ") if event else "",
        progress=stage_progress(run.status, stage),
    )


def run_status_out(session, run, latest_log=_LATEST_LOG_NOT_PROVIDED) -> RunStatusOut:
    latest = get_latest_run_log(session, run.id) if latest_log is _LATEST_LOG_NOT_PROVIDED else latest_log
    stage = latest.stage if latest else run.status
    event = latest.event if latest else ""
    source_states = {
        str(source): str((detail or {}).get("status") or "pending")
        for source, detail in (run.completeness or {}).items()
    }
    return RunStatusOut(
        id=run.id,
        status=run.status,
        current_stage=stage_label(run.status, stage, event),
        stage_detail=event.replace("_", " ") if event else "",
        progress=stage_progress(run.status, stage),
        started_at=run.started_at,
        finished_at=run.finished_at,
        error=run.error,
        cost_estimate=float(run.cost_estimate or 0),
        quarantine_rate=float(run.quarantine_rate or 0),
        source_states=source_states,
    )


def get_or_create_report_snapshot(session, run, actor: Actor) -> Dict:
    """Build a historical report once; new reports are written by synthesis."""
    existing = run.report_snapshot or {}
    if existing.get("version"):
        return existing
    if run.status not in {"done", "partial", "failed"}:
        return {}
    _, company, reviews, themes = get_run_results(session, run.id, actor)
    summary = build_summary(run, reviews, themes)
    summary["cost_rollup"] = get_run_cost_rollup(session, run.id)
    snapshot = build_report_snapshot(company, run, themes, summary, cost_rollup=summary["cost_rollup"])
    run.report_snapshot = snapshot
    session.flush()
    logger.info("Persisted legacy report snapshot for run %s", run.id)
    return snapshot


def stage_label(status: str, stage: str, event: str) -> str:
    if status == "queued":
        return "Queued"
    if status in {"done", "partial", "failed"}:
        return status.capitalize()
    labels = {
        "scraping": "Scraping sources",
        "cleaning": "Cleaning & low-rating selection",
        "theme_discovery": "Discovering themes",
        "classification": "Classifying L1/L2 themes with Gemini Batch",
        "synthesis": "Synthesizing results",
        "budget": "Checking budget",
        "terminal": "Finalizing",
    }
    if event == "llm_batch_progress":
        return "Gemini Batch in progress"
    return labels.get(stage, status.capitalize())


def stage_progress(status: str, stage: str) -> float:
    if status in {"done", "partial", "failed"}:
        return 1
    if status == "queued":
        return 0.02
    return {
        "scraping": 0.18,
        "cleaning": 0.34,
        "theme_discovery": 0.48,
        "classification": 0.68,
        "synthesis": 0.88,
        "budget": 0.92,
        "terminal": 0.96,
    }.get(stage, 0.1)
