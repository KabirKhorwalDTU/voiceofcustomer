# Voice of Customer AI Agent

A cloud-deployable Voice of Customer-to-Deck platform. Operators submit a company and public links, the backend runs a staged ingestion/classification pipeline, persists results to Supabase/Postgres, and the React dashboard exposes charts, downloads, run history, and a deck-spec.

## Apps

- `frontend/`: React + Vite dashboard, deployable to Vercel.
- `backend/`: FastAPI API plus in-process background worker, deployable to Render.
- `data/supabase/schema.sql`: Supabase/Postgres schema.
- `backend/eval/`: Hinglish evaluation fixture and runner.

## Local Quickstart

```bash
cp .env.example .env
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
npm --prefix frontend install

backend/.venv/bin/uvicorn app.main:app --reload --app-dir backend
npm --prefix frontend run dev
```

Without `DATABASE_URL`, the backend uses a local SQLite database at `backend/.local/voc.db`. Production should use the Supabase pooler URL in `DATABASE_URL`.

## Required Production Secrets

- `DATABASE_URL`: Supabase pooler/Postgres URL.
- `APIFY_TOKEN`: Apify API token.
- `GEMINI_API_KEY`: Gemini key for default model.
- `DEEPSEEK_API_KEY`: optional DeepSeek fallback/swap.
- `ALLOW_DEV_LLM_FALLBACK`: keep `false` in production.
- `ALLOW_DEV_INGESTION_FALLBACK`: keep `false` in production.
- `VITE_API_BASE_URL`: deployed backend URL for the Vercel frontend.

## Deployment Status

Frontend production URL: https://frontend-eight-sandy-65.vercel.app

Supabase project: `Voice of Customer AI Agent` (`ojzgfmyoesgzlajwgorh`) in `ap-south-1`.
Supabase URL: `https://ojzgfmyoesgzlajwgorh.supabase.co`.

The database schema has been applied and verified on Supabase. The backend is Render-ready via `render.yaml`; set Render env vars, deploy the backend, then set `VITE_API_BASE_URL` in Vercel and redeploy the frontend.

## Verification

```bash
backend/.venv/bin/python -m pytest backend/tests
backend/.venv/bin/python backend/eval/run_eval.py
npm --prefix frontend run build
```
