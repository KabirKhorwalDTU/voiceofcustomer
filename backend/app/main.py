import math
from typing import List

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from app.config import get_config
from app.db import init_db, session_scope
from app.pipeline.synth import build_deck_spec, build_summary, export_reviews
from app.pipeline.worker import worker
from app.repository import create_run, get_company_runs, get_latest_run_log, get_run, get_run_logs, get_run_results, get_settings, list_runs, query_run_reviews, update_settings
from app.schemas import ResultsOut, ReviewPageOut, RunLogOut, RunOut, SettingsOut, SettingsUpdate, SubmitRunRequest, SubmitRunResponse


app = FastAPI(title="Voice of Customer AI Agent", version="1.0.0")
config = get_config()

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    init_db()
    worker.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    await worker.stop()


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/api/runs", response_model=SubmitRunResponse)
def submit_run(request: SubmitRunRequest) -> SubmitRunResponse:
    with session_scope() as session:
        run, existing = create_run(session, request)
        session.flush()
        return SubmitRunResponse(run=run_out(session, run), deduped_existing=existing)


@app.get("/api/runs", response_model=List[RunOut])
def runs() -> List[RunOut]:
    with session_scope() as session:
        return [run_out(session, run) for run in list_runs(session)]


@app.get("/api/runs/{run_id}", response_model=RunOut)
def run_status(run_id: str) -> RunOut:
    with session_scope() as session:
        run = get_run(session, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        return run_out(session, run)


@app.get("/api/companies/{company_id}/runs", response_model=List[RunOut])
def company_runs(company_id: str) -> List[RunOut]:
    with session_scope() as session:
        return [run_out(session, run) for run in get_company_runs(session, company_id)]


@app.get("/api/runs/{run_id}/results", response_model=ResultsOut)
def results(run_id: str) -> ResultsOut:
    with session_scope() as session:
        try:
            run, company, reviews, themes = get_run_results(session, run_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="run not found") from None
        deck_spec = build_deck_spec(company, run, reviews, themes)
        return ResultsOut(
            company=company,
            run=run_out(session, run),
            reviews=[],
            themes=themes,
            logs=get_run_logs(session, run_id),
            summary=build_summary(run, reviews, themes),
            deck_spec=deck_spec,
        )


@app.get("/api/runs/{run_id}/reviews", response_model=ReviewPageOut)
def run_reviews(
    run_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    source: str = "",
    bucket: str = "",
    theme: str = "",
    rating: str = "",
    q: str = "",
) -> ReviewPageOut:
    with session_scope() as session:
        if not get_run(session, run_id):
            raise HTTPException(status_code=404, detail="run not found")
        rows, total = query_run_reviews(session, run_id, page=page, page_size=page_size, source=source, bucket=bucket, theme=theme, rating=rating, q=q)
        return ReviewPageOut(items=rows, total=total, page=page, page_size=page_size, pages=max(1, math.ceil(total / page_size)))


@app.get("/api/runs/{run_id}/logs", response_model=List[RunLogOut])
def run_logs(run_id: str) -> List[RunLogOut]:
    with session_scope() as session:
        if not get_run(session, run_id):
            raise HTTPException(status_code=404, detail="run not found")
        return [RunLogOut.model_validate(row) for row in get_run_logs(session, run_id)]


@app.get("/api/runs/{run_id}/downloads/{fmt}")
def download(run_id: str, fmt: str) -> Response:
    with session_scope() as session:
        try:
            _, _, reviews, _ = get_run_results(session, run_id)
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
def deck_spec(run_id: str) -> Response:
    with session_scope() as session:
        try:
            run, company, reviews, themes = get_run_results(session, run_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="run not found") from None
        return Response(build_deck_spec(company, run, reviews, themes), media_type="text/markdown")


@app.get("/api/settings", response_model=SettingsOut)
def read_settings() -> SettingsOut:
    with session_scope() as session:
        return SettingsOut.model_validate(get_settings(session))


@app.put("/api/settings", response_model=SettingsOut)
def write_settings(update: SettingsUpdate) -> SettingsOut:
    with session_scope() as session:
        settings = update_settings(session, update.model_dump(exclude_unset=True))
        return SettingsOut.model_validate(settings)


def run_out(session, run) -> RunOut:
    output = RunOut.model_validate(run)
    latest = get_latest_run_log(session, run.id)
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
        "classification": "Classifying with Gemini Batch",
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
