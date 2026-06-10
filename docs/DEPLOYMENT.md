# Deployment Runbook

This repo is designed as a single Git repository with:

- `frontend/` deployed to Vercel.
- `backend/` deployed to Render as a long-running FastAPI web service with an in-process worker.
- Supabase Postgres as the database.

## Current Cloud Resources

- Vercel frontend: https://frontend-eight-sandy-65.vercel.app
- Supabase project: `Voice of Customer AI Agent`
- Supabase project ref: `ojzgfmyoesgzlajwgorh`
- Supabase URL: `https://ojzgfmyoesgzlajwgorh.supabase.co`
- Supabase migration applied: `initial_voice_of_customer_schema`

## Render Backend

Render is intentionally used for the backend because the pipeline can run for minutes and needs a worker process. Do not move the backend to Vercel functions.

Prerequisites:

- This repo pushed to GitHub or GitLab.
- A Render account connected to that Git provider.
- Production secrets:
  - `DATABASE_URL`: Supabase pooler/Postgres URL.
  - `APIFY_TOKEN`
  - `GEMINI_API_KEY`
  - `DEEPSEEK_API_KEY`, optional.
  - `BACKEND_CORS_ORIGINS`: comma-separated frontend origins, including `https://frontend-eight-sandy-65.vercel.app`.

Render setup:

1. Create a Blueprint from the Git repo, or create a web service manually.
2. If using Blueprint, Render reads [`render.yaml`](../render.yaml).
3. Confirm service settings:
   - Root directory: `backend`
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - Health check path: `/health`
4. Keep these production flags:
   - `ALLOW_DEV_LLM_FALLBACK=false`
   - `ALLOW_DEV_INGESTION_FALLBACK=false`

After deploy, copy the Render backend URL.

### GitHub Action Deploy

After the Render service exists, add these GitHub repository secrets:

- `RENDER_API_KEY`
- `RENDER_SERVICE_ID`

Then run the `Deploy Backend To Render` workflow, or push changes under `backend/`.

### Docker Fallback

If Render cannot use the native Python service, create a Docker web service from `backend/Dockerfile`.

Render Docker settings:

- Dockerfile path: `backend/Dockerfile`
- Docker context: `backend`
- Health check path: `/health`
- Start command: use the Dockerfile `CMD`

## Vercel Frontend Finalization

Set `VITE_API_BASE_URL` to the Render backend URL and redeploy:

```bash
VITE_API_BASE_URL=https://YOUR-RENDER-SERVICE.onrender.com ./scripts/set_vercel_api_url.sh
```

The script removes any prior production value, adds the new one, and deploys `frontend/` to production.

## Cloud Smoke Test

Run after Render and Vercel are connected:

```bash
python3 scripts/cloud_smoke.py \
  --api https://YOUR-RENDER-SERVICE.onrender.com \
  --frontend https://frontend-eight-sandy-65.vercel.app
```

The smoke test checks:

- Backend `/health`.
- API settings endpoint.
- Run submission and polling to a terminal state.
- Results endpoint.
- CSV, JSON, and XLSX download endpoints.
- Frontend HTTP 200.

If production ingestion secrets are missing, runs should terminate as `partial` with source completeness details rather than silently using local sample data.

## Production Environment Template

Use [`.env.production.example`](../.env.production.example) as the non-secret checklist for Render and Vercel.

## Known External Blocker

The current Codex environment can create/migrate Supabase and deploy Vercel, but it does not expose Render credentials or a GitHub remote target for this new repository. Backend deployment therefore requires either:

- A pushed Git repo connected to Render, or
- Render API/deploy access provided to this environment.
