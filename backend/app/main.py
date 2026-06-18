import asyncio
import logging
import math
from typing import List

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from app.auth import Actor, clean_guest_id, create_or_get_user, create_user_session, resolve_actor
from app.config import get_config
from app.db import init_db, session_scope
from app.models import User
from app.pipeline.synth import build_deck_spec, build_summary, export_reviews
from app.pipeline.worker import worker
from app.repository import (
    can_access_run,
    claim_guest_workspace,
    create_run,
    delete_run_by_id,
    get_company_runs,
    get_latest_run_log,
    get_latest_run_logs,
    get_run_cost_rollup,
    get_run,
    get_run_logs,
    get_run_results,
    get_settings,
    list_actor_runs,
    list_runs,
    query_run_reviews,
    rerun_company_from_run,
    update_settings,
)
from app.schemas import (
    AuthLoginRequest,
    AuthLoginResponse,
    ResultsOut,
    ReviewPageOut,
    RunLogOut,
    RunOut,
    SettingsOut,
    SettingsUpdate,
    SubmitRunRequest,
    SubmitRunResponse,
    UserOut,
)


_LATEST_LOG_NOT_PROVIDED = object()
app = FastAPI(title="Voice of Customer AI Agent", version="1.0.0")
config = get_config()
logger = logging.getLogger(__name__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    app.state.bootstrap_ready = False
    app.state.bootstrap_error = ""
    app.state.bootstrap_task = asyncio.create_task(bootstrap_backend())


@app.on_event("shutdown")
async def shutdown() -> None:
    task = getattr(app.state, "bootstrap_task", None)
    if task and not task.done():
        task.cancel()
    await worker.stop()


@app.get("/health")
def health() -> dict:
    return {"ok": True, "bootstrap_ready": bool(getattr(app.state, "bootstrap_ready", False))}


def header_actor(session, authorization: str, x_guest_id: str, x_operator_mode: str) -> Actor:
    return resolve_actor(session, authorization=authorization, guest_id=x_guest_id, operator_mode=x_operator_mode)


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


@app.post("/api/auth/login", response_model=AuthLoginResponse)
def login(request: AuthLoginRequest) -> AuthLoginResponse:
    with session_scope() as session:
        user = create_or_get_user(session, request.email)
        claimed_runs = claim_guest_workspace(session, clean_guest_id(request.guest_id), user.id)
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


@app.get("/api/runs", response_model=List[RunOut])
def runs(
    authorization: str = Header(default=""),
    x_guest_id: str = Header(default=""),
    x_operator_mode: str = Header(default=""),
) -> List[RunOut]:
    with session_scope() as session:
        actor = header_actor(session, authorization, x_guest_id, x_operator_mode)
        if actor.is_operator:
            run_rows = list_runs(session)
        elif actor.user_id or actor.guest_id:
            run_rows = list_actor_runs(session, actor)
        else:
            run_rows = []
        latest_logs = get_latest_run_logs(session, [run.id for run in run_rows])
        return [run_out(session, run, latest_logs.get(run.id)) for run in run_rows]


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
        if not run or not can_access_run(run, actor):
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
        try:
            run, company, reviews, themes = get_run_results(session, run_id, actor)
        except KeyError:
            raise HTTPException(status_code=404, detail="run not found") from None
        summary = build_summary(run, reviews, themes)
        summary["cost_rollup"] = get_run_cost_rollup(session, run_id)
        deck_spec = build_deck_spec(company, run, reviews, themes, summary=summary)
        return ResultsOut(
            company=company,
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
        if not run or not can_access_run(run, actor):
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
        try:
            run, company, reviews, themes = get_run_results(session, run_id, actor)
        except KeyError:
            raise HTTPException(status_code=404, detail="run not found") from None
        return Response(build_deck_spec(company, run, reviews, themes), media_type="text/markdown")


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


def run_out(session, run, latest_log=_LATEST_LOG_NOT_PROVIDED) -> RunOut:
    output = RunOut.model_validate(run)
    latest = get_latest_run_log(session, run.id) if latest_log is _LATEST_LOG_NOT_PROVIDED else latest_log
    stage = latest.stage if latest else run.status
    event = latest.event if latest else ""
    output.current_stage = stage_label(run.status, stage, event)
    output.stage_detail = event.replace("_", " ") if event else ""
    output.progress = stage_progress(run.status, stage)
    return output


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
