# DECISIONS

## Adopted Answers

- Backend host: Render.
- Queue/worker: lightweight Postgres-backed run state with one in-process async worker for v1. Redis/RQ/Celery is deferred until horizontal scaling.
- Frontend host: Vercel.
- Database: Supabase managed Postgres, accessed by the backend through `DATABASE_URL`.
- Visual direction: restrained operator-console SaaS UI because no visual reference or saved Product Design context was available.
- LLM default: Gemini 2.5 Flash through the gateway. DeepSeek V3 is configurable from settings. A deterministic development fallback is enabled only when provider keys are absent and `ALLOW_DEV_LLM_FALLBACK=true`.

## Deployment Status

- Frontend production deployment: https://frontend-eight-sandy-65.vercel.app
- Latest deployment URL: https://frontend-c1vblmnn8-kabir-khorwals-projects.vercel.app
- Vercel project: `frontend`.
- Vercel SSO deployment protection was disabled after the first public check returned HTTP 401; the final public check returned HTTP 200.
- Supabase project: `Voice of Customer AI Agent` (`ojzgfmyoesgzlajwgorh`) in `ap-south-1`.
- Supabase URL: `https://ojzgfmyoesgzlajwgorh.supabase.co`.
- Supabase schema migration `initial_voice_of_customer_schema` was applied and verified. Tables present: `companies`, `runs`, `reviews`, `settings`, `themes`. The singleton settings row is present with Gemini defaults.
- Backend deployment is prepared through `render.yaml`, but was not pushed to Render because no Render CLI/token/project or GitHub remote target was available in the environment.
- The deployed frontend currently needs `VITE_API_BASE_URL` set to the eventual Render backend URL and a redeploy before it can operate against the cloud backend. Until that is configured, production shows an API configuration error instead of calling localhost.

## Apify Actor Pins

Exact actor build/version metadata should be resolved from Apify once `APIFY_TOKEN` is available. The v1 config records actor IDs and keeps all actor access centralized in `backend/app/pipeline/apify.py`.

- Google Play reviews: `neatrat/google-play-store-reviews-scraper`
- Apple App Store reviews: `thewolves/appstore-reviews-scraper`
- Reddit keyword search: `trudax/reddit-scraper`
- Google Maps shallow reviews: `compass/google-maps-reviews-scraper`
- MouthShut reviews: `getdataforme/mouthshut-reviews-scraper`

## Processing Defaults

- MinHash/LSH library: `datasketch`.
- Near-duplicate threshold: `0.86`.
- Text shingles: 5 words.
- Theme discovery sample size: 300 reviews, stratified across source and rating.
- Default per-run budget: `$1.00`.
- Default source weights: equal weights for `play`, `appstore`, `reddit`, `maps`, and `mouthshut`.
- Default max reviews: 3000 for app-store sources; shallow caps are applied to Maps, Reddit, and MouthShut in the scraper stage.
- Recency window: 90 days.
- Batch size: 25 reviews per LLM call.

## Hinglish Eval

Run:

```bash
python backend/eval/run_eval.py
```

The eval uses the same gateway interface as the production classifier. When no model key is configured it runs against the deterministic development adapter so CI can still verify schema and label plumbing. Record the latest score after running verification.

Latest local run:

```json
{
  "fixture_count": 30,
  "bucket_accuracy": 0.7667,
  "severity_accuracy": 0.9333,
  "weighted_score": 0.8083,
  "provider": "gemini",
  "model": "gemini-2.5-flash",
  "dev_fallback": true
}
```
