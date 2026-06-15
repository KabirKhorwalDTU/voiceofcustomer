# Voice of Customer Platform - Technical PM Learning Guide

Last updated: 2026-06-15

This document explains the technical stack used in the VoC platform, why each piece exists, how data moves through the system, what can fail, and how to reason about operations/costs. It is written for a technical PM who understands APIs and databases but wants to understand the infrastructure and engineering choices well enough to manage, debug, and evolve the product.

## 1. Product In One Sentence

The platform takes a company plus public review links, collects recent low-rated customer feedback, classifies it into L1 themes and L2 sub-issues using Gemini Batch, stores everything in Supabase Postgres, and shows a dashboard/results page with quotes, exports, costs, and a deck spec.

## 2. The Main Pieces

| Layer | Technology | Why it exists | What to know as PM |
| --- | --- | --- | --- |
| Frontend | React + Vite, hosted on Vercel | Browser UI for submissions, run tracking, charts, tables, exports | Vercel serves static files globally. It does not run the long scraping/classification jobs. |
| Backend API | FastAPI + Uvicorn, hosted on Render | REST API for creating runs, polling status, fetching results, downloads, logs | Render keeps a long-running Python process alive. This is needed because jobs can take minutes. |
| Worker | In-process async worker inside FastAPI app | Processes queued runs sequentially | The worker watches Postgres for `queued` runs and processes one company at a time. |
| Database | Supabase Postgres | System of record for companies, runs, reviews, themes, settings, logs | Everything important is persisted here. If the UI disagrees with DB, DB wins. |
| Store ingestion | OSS Node libraries | Pulls Play Store and App Store reviews without paid Apify cost | These run from backend code through Node packages. |
| Maps ingestion | Google Places API + Apify Maps scraper | Finds correct physical locations and scrapes Maps reviews | Places API resolves place IDs; Apify gets review volume. |
| Reddit ingestion | Apify Reddit actor, optional | Can fetch social posts but quality/cost was weak | Keep optional. It is not part of the default recommended workflow. |
| LLM | Gemini 3.1 Flash-Lite Batch API | Discovers L1/L2 taxonomy and classifies reviews | Batch is cheaper and avoids sync rate-limit pain. |
| Deployment CI | GitHub + GitHub Actions + Render API | Push code, run tests, deploy backend | GitHub is the source of truth. Render deployment may need manual/API trigger if autodeploy is off. |

## 3. High-Level Architecture

```mermaid
flowchart LR
  User["Operator in browser"] --> FE["React app on Vercel"]
  FE --> API["FastAPI API on Render"]
  API --> DB[("Supabase Postgres")]
  API --> Worker["In-process worker"]
  Worker --> DB
  Worker --> Play["Google Play OSS scraper"]
  Worker --> AppStore["App Store OSS scraper"]
  Worker --> Places["Google Places API"]
  Worker --> Apify["Apify Maps/Reddit actors"]
  Worker --> Gemini["Gemini Batch API"]
  Gemini --> Worker
  Apify --> Worker
  Worker --> DB
  FE --> API
```

The important idea: Vercel is only the UI. Render owns the long-running backend process. Supabase is the memory of the product.

## 4. Runtime Flow

### 4.1 Submit A Company

The operator enters:

| Field | Example | Used for |
| --- | --- | --- |
| Company name | Snabbit | Display, matching, query labels |
| Play Store URL | `play.google.com/store/apps/details?id=...` | Extract Play app ID |
| App Store URL | `apps.apple.com/.../id...` | Extract App Store app ID |
| Website | `https://snabbit.com` | Extract domain and brand keyword |
| Maps toggle/location | enabled, Bangalore India | Decide whether to run Maps |
| Reddit toggle | false | Decide whether to run Reddit |

Backend creates or updates a `companies` row and creates a `runs` row with status `queued`.

### 4.2 Queue Model

Current v1 queue is simple:

| Concept | Implementation |
| --- | --- |
| Queue | `runs.status = 'queued'` in Postgres |
| Worker | Python async loop in `backend/app/pipeline/worker.py` |
| Concurrency | One company at a time |
| Why sequential | Cost control, lower provider stress, easier overnight operation |
| Job dedup | If same company has active run, API returns existing active run |

This is not a separate queue service like Redis/RQ/Celery. It is enough for v1 because overnight throughput is modest and the worker state is persisted in Postgres.

### 4.3 Run Stages

| Stage | Status/log signal | What happens |
| --- | --- | --- |
| Queue | `run_queued` | Run row created |
| Scraping | `scraping` | Store/Maps/optional Reddit reviews collected |
| Cleaning | `dedup_completed` | Text normalized, duplicates removed, only 1/2/3-star rated reviews selected |
| Theme discovery | `theme_discovery` | Gemini creates L1/L2 taxonomy from selected reviews |
| Classification | `classification` | Gemini assigns every selected row to L1/L2 |
| Synthesis | `themes_built` | Counts, shares, top quotes, source ROI built |
| Terminal | `done`/`partial`/`failed` | Run is completed or failed |

## 5. Frontend: React On Vercel

### What Vercel Does

Vercel hosts the compiled frontend as static assets:

| Thing | Meaning |
| --- | --- |
| Build output | HTML/CSS/JS files generated by Vite |
| Production URL | `https://frontend-eight-sandy-65.vercel.app` |
| Vercel cache | Serves unchanged assets fast |
| API calls | Browser calls Render backend, not Vercel functions |

### Why Vercel Is Not The Backend

The pipeline can take several minutes per company. Serverless functions are not a good fit for long scraping/LLM jobs. So Vercel is only the UI shell.

### Important UI Screens

| Screen | Purpose |
| --- | --- |
| Dashboard | Active runs, run history, spend/capacity, rerun/delete |
| New Analysis | Submit company |
| Results page | Company-level themes, L1/L2 tree, source ROI, tagged reviews, downloads, deck spec |

## 6. Backend: FastAPI On Render

### What FastAPI Does

FastAPI exposes REST endpoints:

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Health check for Render and humans |
| `POST /api/runs` | Create a company run |
| `GET /api/runs` | List run history |
| `GET /api/runs/{id}` | Poll one run |
| `POST /api/runs/{id}/rerun` | Create complete rerun for same company |
| `DELETE /api/runs/{id}` | Delete non-active run |
| `GET /api/runs/{id}/results` | Full results payload |
| `GET /api/runs/{id}/reviews` | Paginated/filterable tagged reviews |
| `GET /api/runs/{id}/logs` | Detailed journey logs |
| `GET /api/runs/{id}/downloads/{fmt}` | JSON/CSV/XLSX exports |
| `GET /api/runs/{id}/deck-spec.md` | Markdown deck spec |

### What Render Does

Render runs the Python backend as a web service:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Render gives the app:

| Render concept | Meaning |
| --- | --- |
| Service | The deployed backend app |
| Deploy | A build/release from a Git commit |
| Env vars | Secrets/config injected into the process |
| Health check | Render pings `/health` |
| Logs | stdout/stderr from backend |

### Why Render Instead Of Vercel Functions

The worker polls Gemini Batch and waits for scrapers. A job can take minutes. Render gives us a long-lived process; Vercel functions are optimized for request/response work.

## 7. Supabase Postgres

### What Supabase Is Here

Supabase is managed Postgres. We use it as a normal database, not as a frontend client database.

The backend connects using the Supabase pooler:

| Piece | Meaning |
| --- | --- |
| Host | Supabase pooler host |
| Port | Transaction pooler port, usually 6543 |
| Database | `postgres` |
| User/password | Database login credentials |
| Pooler | Sits between app and database to manage connections |

### Why The Password Matters

The database password is not an app login. It is the credential that lets the backend connect to Postgres. Anyone with it can potentially read/write the DB if network/project rules allow it. That is why it belongs only in Render env vars or local `.env`, not in GitHub.

### Tables

| Table | Purpose |
| --- | --- |
| `companies` | One row per company/app/domain |
| `runs` | One row per pipeline run |
| `reviews` | Tagged review rows for a run |
| `themes` | Aggregated L1 themes and nested L2 subthemes |
| `settings` | Provider/model/max reviews/budget settings |
| `run_logs` | Journey logs, costs, retries, token usage, failure reasons |

### Important Data Ownership Rule

The backend owns database writes. The frontend never talks directly to Supabase. This keeps secrets out of the browser and keeps business logic centralized.

## 8. SQLAlchemy And Psycopg

The backend uses:

| Library | Role |
| --- | --- |
| SQLAlchemy | Python ORM/query layer |
| psycopg | Postgres driver |

SQLAlchemy maps Python classes like `Run`, `Review`, and `Theme` to tables. Psycopg is the lower-level driver that actually talks to Postgres.

One production detail: Supabase transaction pooler does not preserve backend sessions for prepared statements, so the app disables automatic psycopg preparation with `prepare_threshold=None`.

## 9. Ingestion Sources

### Play Store

| Detail | Current behavior |
| --- | --- |
| Tool | `facundoolano/google-play-scraper` |
| Cost | Free from our app perspective |
| Language | Pulls Hindi + English where configured |
| Selection | Low-rated 1/2/3-star reviews only |
| Cap | Settings max reviews, currently 5000 |

### App Store

| Detail | Current behavior |
| --- | --- |
| Tool | `facundoolano/app-store-scraper` |
| Cost | Free from our app perspective |
| Cap | 500 raw reviews |
| Selection | Low-rated 1/2/3-star reviews only |

### Google Maps

Maps is two-step:

1. Google Places API finds correct place IDs.
2. Apify Maps scraper pulls review volume from those places.

| Detail | Current behavior |
| --- | --- |
| Places API | Used for entity resolution, not review volume |
| Query | Brand + India/location hint |
| Maps scraper | Apify `compass/google-maps-reviews-scraper` |
| Sort | Lowest rating |
| Cap | 100 reviews |
| Cost | Around USD 0.0006/review from Apify event pricing |

### Reddit

Reddit is optional and currently not recommended as default.

| Reason | Practical impact |
| --- | --- |
| Cost per useful row can be high | Bad ROI for many brands |
| Search quality varies | Many irrelevant posts |
| Useful for very public brands only | Keep as opt-in |

## 10. Cleaning, Dedup, And Selection

### Cleaning

Text is normalized before storage/classification:

| Step | Why |
| --- | --- |
| Collapse whitespace | Cleaner prompts and UI |
| Remove NUL/control chars | Postgres rejects NUL bytes |
| Drop empty reviews | Avoid wasting Gemini tokens |

The 2026-06-15 Noon failure happened because a scraped review contained a NUL byte. Postgres rejected the insert. This is now fixed at the cleaner layer.

### Dedup

The app uses MinHash/LSH:

| Concept | Meaning |
| --- | --- |
| Exact dedup | Same source/text/date hash |
| Near dedup | Similar review text detected by MinHash |
| Why not embeddings | Dedup should remove near-identical spam, not semantic themes |

### Selection

Only reviews likely to contain problems are sent into analysis:

| Source type | Selection rule |
| --- | --- |
| Rated sources | Rating 1, 2, or 3 |
| Reddit | Included if enabled, because posts do not have app-store star ratings |

## 11. Gemini And Batch API

### Why Gemini Batch

| Path | Pros | Cons |
| --- | --- | --- |
| Sync API | Immediate response | More rate-limit pressure, higher cost |
| Batch API | Cheaper, async, fewer rate problems | Can take longer and needs polling |

The product currently uses Gemini Batch by default and records `sync_fallback=false`.

### Prompt Shape

Taxonomy discovery input:

```json
{
  "task": "discover_l1_l2_taxonomy",
  "reviews": [[1, 1, "review text"]],
  "row_format": "[row_id, rating, text]"
}
```

Classification input:

```json
{
  "task": "classify_reviews_l1_l2",
  "theme_set": [{"l1_theme": "booking_unavailability", "l2_subthemes": ["slots_always_full"]}],
  "reviews": [[1, 1, "review text"]],
  "output_format": "[row_id, l1_theme, l2_theme]"
}
```

Classification output:

```json
[
  [1, "booking_unavailability", "slots_always_full"]
]
```

Fields removed to reduce token cost:

| Removed field | Why |
| --- | --- |
| `source` | Not needed for classification |
| `date` | Not needed for L1/L2 |
| `review_hash` | Replaced by compact row ID |
| `language` | Not needed downstream |
| `english_gloss` | Good for readability but expensive; raw quotes are acceptable |
| `severity` | Removed by product decision |
| `bucket` | Product moved to pure L1/L2 |

## 12. L1/L2 Theme Model

The current product model is:

```text
L1 theme -> L2 sub-issue -> review rows and quotes
```

Example:

| L1 | L2 |
| --- | --- |
| `booking_unavailability` | `slots_always_full` |
| `booking_unavailability` | `service_not_available_in_area` |
| `refund_and_payment_issues` | `denied_or_delayed_refunds` |

Quality gate:

| Metric | Target |
| --- | --- |
| L1 `other` share | Below 15% |
| Quarantine rate | Near 0% |

If L1 `other` exceeds 15%, the app runs one repair pass on the `other` rows.

## 13. Cost Model

Costs are tracked at two layers:

| Cost source | Where recorded |
| --- | --- |
| Apify | `run_logs.cost_usd`, `runs.cost_estimate` |
| Gemini | Token usage from API response, converted by pricing table |
| Play/App Store OSS | Recorded as zero direct provider cost |
| Google Places API | Not currently attributed in app cost if within free/console billing |

Current settings:

| Setting | Value |
| --- | --- |
| Model | `gemini-3.1-flash-lite` |
| Batch size | 100 |
| Max reviews | 5000 |
| Run budget cap | USD 1 |
| Maps cap | 100 |
| Reddit | Optional/off by default |

Example verified Snabbit run:

| Metric | Value |
| --- | --- |
| Classified rows | 750 |
| Gemini tokens | 96,597 |
| Gemini cost | USD 0.022958 |
| Apify Maps cost | USD 0.060000 |
| Total cost | USD 0.083000 |
| Quarantine | 0% |
| Other share | 9.73% |

## 14. Logs And Observability

The `run_logs` table is the main debugging surface.

Each log row can contain:

| Field | Meaning |
| --- | --- |
| `stage` | scraping, cleaning, theme_discovery, classification, synthesis, terminal |
| `event` | What happened |
| `status` | ok, info, warning, failed |
| `source` | play/appstore/maps/reddit/mouthshut if source-specific |
| `provider` | Gemini, Apify, OSS, etc. |
| `cost_usd` | Cost attributed to that event |
| `input_tokens` | Gemini input tokens |
| `output_tokens` | Gemini output tokens |
| `details` | JSON payload with retries, errors, places, theme set, batch progress |

The dashboard intentionally hides journey logs from the main UI, but the backend keeps them for debugging.

## 15. What Happened On 2026-06-15

### Symptoms

| Symptom | Companies |
| --- | --- |
| Stuck in `Gemini Batch in progress` for 8-10 hours | First Club, Pronto, Bazaar Now, Hyuga Lifa, Oolka, One Percent Club |
| Failed | Noon |

### Root Cause 1: Stale Active Runs

The worker runs inside the Render web process. If the process restarts or dies while a run is already `classifying`, the run remains `classifying` in Postgres. The old code only picked `queued` runs. Therefore stale active runs could sit forever.

Fix:

| Fix | Behavior |
| --- | --- |
| Stale-run recovery | If an active run has no fresh logs for 30 minutes, reset it to `queued` |
| Output cleanup | Delete partial reviews/themes before restarting that run |
| Ops log | Add `stale_active_run_requeued` with prior status and last event |

### Root Cause 2: Noon NUL Byte

Noon failed because a scraped review contained a NUL byte (`0x00`). Postgres text fields cannot store NUL bytes.

Fix:

| Fix | Behavior |
| --- | --- |
| Cleaner sanitizer | Removes NUL and unsafe control characters before DB insert |
| Regression test | Proves NUL-byte review text becomes safe |

## 16. Deployment Flow

### GitHub

GitHub is the code source of truth.

Common flow:

```bash
git add ...
git commit -m "Message"
git push origin main
```

### Backend Deploy

The backend deploy is Render. A push to GitHub may or may not automatically deploy depending on Render settings. If not, a deploy can be triggered via Render API.

Checks:

| Check | Purpose |
| --- | --- |
| Git commit hash | Did the right code reach GitHub? |
| Render deploy commit | Did Render deploy the same commit? |
| `/health` | Did backend boot? |
| Supabase logs | Did worker start and process queued runs? |

### Frontend Deploy

The frontend deploy is Vercel. Vercel serves the React build. Frontend changes require a Vercel deploy; backend-only changes do not.

## 17. CAP And Reliability Thinking

CAP theorem says distributed systems cannot perfectly maximize consistency, availability, and partition tolerance at the same time. For this product:

| Area | Choice |
| --- | --- |
| Source of truth | Supabase Postgres |
| Consistency | Prefer DB consistency over UI optimism |
| Availability | Partial-source success keeps runs usable when one source fails |
| Partition/failure handling | Logs, partial status, stale-run recovery |

The product should never silently pretend a failed source succeeded. It should surface completeness and continue where possible.

## 18. PM Debugging Playbook

### If A Run Is Stuck

Check:

1. Run status: `queued`, `scraping`, `classifying`, `done`, `partial`, `failed`.
2. Latest `run_logs` event.
3. Whether latest log is fresh.
4. Whether Render recently deployed/restarted.
5. Whether Gemini Batch operation is still polling.

Interpretation:

| Observation | Likely meaning |
| --- | --- |
| Fresh `batch_poll` logs | Worker is alive; wait |
| No logs for 30+ minutes | Stale active run; recovery should requeue |
| `run_failed` with provider error | Source/API failure |
| `run_failed` with DB error | Data sanitation/schema issue |

### If A Run Failed

Read `run.error` and latest `run_logs.details.error`.

Common categories:

| Error type | Meaning | Usual fix |
| --- | --- | --- |
| Gemini 429/503 | Provider throttling/outage | Retry/backoff/batch |
| Apify 400 | Actor input schema wrong | Fix actor payload |
| Apify 403 | Token/proxy/permission issue | Check Apify account/actor |
| Postgres error | Bad data or schema mismatch | Sanitize/migrate |
| Budget exceeded | Run cap hit | Reduce sources/reviews or raise cap |

### If Cost Looks Wrong

Check:

1. `runs.cost_estimate`
2. `run_logs` grouped by provider/source
3. Gemini input/output tokens
4. Apify event counts
5. Whether Reddit/Maps were enabled

## 19. What To Know Before Next Phase

Deck generation and email outreach will add new product surfaces:

| Phase | Additional tech likely needed |
| --- | --- |
| Deck rendering | PPTX generator, Gamma/Chronicle API, or Google Slides API |
| Email | Resend/SendGrid/Gmail API |
| Prospecting | Apollo API, company/contact enrichment |
| Review queue | Human approval state in DB |
| Auth | Simple allowlist or password gate |

For cold-email scale, the next important PM question is not just "can we generate insights?" It is "can we generate an accurate, approved, source-backed outbound artifact for every company without manual rework?"

## 20. Glossary

| Term | Meaning |
| --- | --- |
| API | A contract for one system to call another system |
| Backend | Server-side application that owns business logic |
| Frontend | Browser UI |
| Database | Persistent storage |
| Postgres | Relational database used by Supabase |
| Pooler | Connection manager between backend and Postgres |
| Env var | Secret/config injected into runtime |
| Render | Backend hosting platform |
| Vercel | Frontend hosting platform |
| Worker | Background processor for queued jobs |
| Queue | Ordered list of jobs waiting to be processed |
| Batch API | Async LLM job API where we submit requests and poll later |
| Token | Unit of text billing/processing for LLMs |
| Apify actor | Hosted scraper packaged as an API product |
| Place ID | Google Maps identifier for a physical location |
| Dedup | Removing duplicate or near-duplicate reviews |
| L1 theme | Main issue category |
| L2 sub-issue | Specific issue inside an L1 theme |
| Quarantine | Rows/batches that could not be confidently classified |
| Other share | Percentage of rows assigned to generic `other` |
