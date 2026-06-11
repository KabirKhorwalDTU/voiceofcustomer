# DECISIONS

## v5 Adopted Answers

- Backend host: Render.
- Queue/worker: lightweight Postgres-backed run state with one in-process async worker for v1. Redis/RQ/Celery is still the right next step before horizontal worker scaling.
- Default batch size: 100.
- MouthShut: disabled by default, with the scraper seam/config left in place.
- Second high-volume test company: Paytm.
- Maps: opt-in per company. Pronto was run with Maps on; Paytm was run with Maps off.

## Current Deployment

- Frontend: `https://frontend-eight-sandy-65.vercel.app`
- Backend: `https://voc-ai-agent-api.onrender.com`
- Supabase project: `ojzgfmyoesgzlajwgorh`
- GitHub repo: `KabirKhorwalDTU/voiceofcustomer`
- Latest backend hardening commit deployed to Render: `b044ff6`
- Latest frontend production deploy still points to the Render backend and returns HTTP 200.

## Ingestion Decisions

- Google Play is now OSS-primary through `facundoolano/google-play-scraper` version `10.0.0`.
- Play fetches both `lang='hi'` and `lang='en'`, `country='in'`, newest-first, then merges and dedups.
- App Store is now OSS-primary through `facundoolano/app-store-scraper` version `0.18.0`.
- App Store page count is capped at the library maximum of 10 pages, so the v1 observed cap is about 500 reviews.
- App-store Apify fallbacks remain configured:
  - Play fallback: `neatrat/google-play-store-reviews-scraper`
  - App Store fallback: `thewolves/appstore-reviews-scraper`
- Reddit actor changed to `harshmaur/reddit-scraper`, capped at 100 posts, best-effort.
- Google Maps uses Places API Text Search before the Apify Maps actor; if Places fails or yields no accepted place IDs, it does not scrape generic brand-name matches.
- MouthShut remains disabled by default: `getdataforme/mouthshut-reviews-scraper` with version marker `disabled-by-default`.

## LLM Decisions

- Default model: `gemini-3.1-flash-lite`.
- Batch API probe was attempted first.
- Batch path result: Gemini Batch returned HTTP 400 for `models/gemini-3.1-flash-lite:batchGenerateContent`, so the gateway used synchronous fallback.
- Synchronous fallback uses the global 13 RPM limiter and exponential backoff. It no longer quarantines on the first 429/503.
- At live scale, Gemini still returned repeated HTTP 429s. The worker now bounds whole classification and completes with explicit low-confidence/quarantined heuristic tags instead of hanging.
- Low-confidence UI gate remains `quarantine_rate > 0.20`.

## Hinglish Eval

Real Flash-Lite eval command:

```bash
cd backend
ALLOW_DEV_LLM_FALLBACK=false GEMINI_API_KEY=... .venv/bin/python eval/run_eval.py
```

Result:

```json
{
  "fixture_count": 30,
  "bucket_accuracy": 0.7667,
  "severity_accuracy": 0.9333,
  "per_class_accuracy": {
    "complaint": 1.0,
    "feature_request": 0.2222,
    "praise": 1.0
  },
  "weighted_score": 0.8083,
  "provider": "gemini",
  "model": "gemini-3.1-flash-lite",
  "dev_fallback": false
}
```

Observation: complaint and praise labels are strong in the small eval, but feature-request recall is weak at batch size 100 and should be monitored. I did not reduce the default to 50 because live scale was dominated by provider 429s rather than eval-format degradation.

## Live Verification Runs

### Pronto

- Run ID: `fba82422-2085-4c24-9266-3c6d449007fa`
- Results URL: `https://frontend-eight-sandy-65.vercel.app/runs/fba82422-2085-4c24-9266-3c6d449007fa`
- Backend results: `https://voc-ai-agent-api.onrender.com/api/runs/fba82422-2085-4c24-9266-3c6d449007fa/results`
- Status: `partial`
- Wall-clock: 145.2 seconds in the final explicit processor run
- Cost estimate: `$0.2205`
- Raw source counts: Play `1805`, App Store `400`, Reddit `0`, Maps `0`, MouthShut `0`
- Stored review rows after dedup: `1353`
- Dedup ratio: `0.3864`
- Quarantine rate: `1.0`
- Play Hindi/Hinglish check: 225 Play rows contained Hindi/Hinglish/non-ASCII indicators.
- Completeness:
  - Play: `ok`, OSS primary.
  - App Store: `ok`, OSS primary.
  - Maps: `failed`, Places API returned HTTP 403; no generic Pronto places were scraped.
  - Reddit: `failed`, Apify actor returned HTTP 400 on all 3 attempts.
  - MouthShut: `disabled`.
- Downloads verified: CSV, JSON, XLSX all HTTP 200.
- Deck-spec endpoint verified: HTTP 200.

### Paytm

- Run ID: `4f6b3d92-8002-4e93-9a77-079ee36a7e50`
- Results URL: `https://frontend-eight-sandy-65.vercel.app/runs/4f6b3d92-8002-4e93-9a77-079ee36a7e50`
- Backend results: `https://voc-ai-agent-api.onrender.com/api/runs/4f6b3d92-8002-4e93-9a77-079ee36a7e50/results`
- Status: `partial`
- Wall-clock: 956.6 seconds in the final explicit processor run
- Cost estimate: `$0.3500`
- Raw source counts: Play `3000`, App Store `500`, Reddit `0`, Maps `0`, MouthShut `0`
- Stored review rows after dedup: `1992`
- Dedup ratio: `0.4309`
- Quarantine rate: `1.0`
- Play Hindi/Hinglish check: 713 Play rows contained Hindi/Hinglish/non-ASCII indicators.
- Completeness:
  - Play: `ok`, OSS primary.
  - App Store: `ok`, OSS primary.
  - Maps: `disabled` for this company.
  - Reddit: `failed`, Apify actor returned HTTP 400 on all 3 attempts.
  - MouthShut: `disabled`.
- Downloads verified: CSV, JSON, XLSX all HTTP 200.
- Deck-spec endpoint verified: HTTP 200.

## What Went Right

- The platform remains end-to-end deployable: Vercel frontend, Render backend, Supabase persistence.
- Store ingestion is fixed: Play and App Store now work without Apify for the critical app-store sources.
- Play hi+en merging worked; Hindi/Hinglish reviews are present in both live runs.
- Per-source failure behavior worked: Reddit and Maps failures did not fail the whole run.
- Maps no longer pulls wrong generic Pronto reviews when Places discovery is unavailable.
- Run logs persist source attempts, retry counts, failure reasons, providers, model path, cost estimates, dedup ratio, and terminal summaries.
- Downloads and deck-spec endpoints work for both final runs.
- The UI can show low-confidence results because quarantine is surfaced.

## What Went Wrong / Remaining Gaps

- The provided Google Maps key returned HTTP 403 for Places API Text Search. Pronto Maps stayed failed, but safely did not scrape wrong places.
- The Reddit Apify actor returned HTTP 400 for the current input shape. Its actor metadata did not expose an input schema through the Apify API, so this remains a best-effort source failure.
- Gemini Batch returned HTTP 400 for the configured model endpoint, so classification used sync fallback.
- Gemini sync fallback still hit repeated HTTP 429s at live scale. The system now completes with low-confidence heuristic tags, but the theme assignments are not trustworthy when `quarantine_rate = 1.0`.
- The free Render in-process worker can race with deploy restarts. I used an explicit final-code processor against Supabase for the final evidence runs. For production scale, move queue execution to a durable worker/Redis queue or disable zero-downtime deploy pickup during long jobs.
- The final low-confidence runs collapse themes to broad `other` buckets because classification was quarantined.

## Follow-Up Recommendation

- Rotate and restrict exposed keys.
- Enable billing/credits or use DeepSeek V3 for live classification scale.
- Fix Reddit actor input against the actor's current documented schema or select a replacement actor with an exposed schema.
- Add per-batch progress logs inside the LLM gateway.
- Move v2 worker execution to Redis/RQ or Celery so deploys cannot interrupt in-process jobs.
