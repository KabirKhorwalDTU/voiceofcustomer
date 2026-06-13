# DECISIONS

## v5 Final Status

- Result: successful final-leg hardening.
- Backend: Render, `https://voc-ai-agent-api.onrender.com`.
- Frontend: Vercel, `https://frontend-eight-sandy-65.vercel.app`.
- Database: Supabase project `ojzgfmyoesgzlajwgorh`.
- Repository: `KabirKhorwalDTU/voiceofcustomer`.
- Final code commit verified in production before this document update: `4435e7c`.
- Final live runs:
  - Pronto: `d108c265-4e9e-4c27-8125-0db0c1cc90e0`.
  - Paytm: `8b1174a5-096d-4b73-b26b-89723d6245e0`.

## Adopted Answers

- Default batch size: `100`.
- MouthShut: disabled by default, seam left in config.
- Second high-volume test company: Paytm.
- Maps: opt-in per company. Pronto was run with Maps on and `maps_location_hint = "Mumbai"`. Paytm was run with Maps off.
- LLM model: `gemini-3.1-flash-lite`, selected through settings/config.

## Official Request Shape Checks

- Gemini Batch API was verified against the official Gemini Batch API reference. The gateway uses `models/{model}:batchGenerateContent`, wraps requests in `batch.inputConfig.requests.requests`, and uses `generationConfig.responseMimeType = "application/json"`.
- Places Text Search (New) was verified against the official Google Places Web Service docs. Discovery uses `POST https://places.googleapis.com/v1/places:searchText`, JSON body `{ "textQuery": "<brand> <city>" }`, and `X-Goog-FieldMask`.
- Reddit input schema came from the operator-verified Apify actor run/readme screenshot for `harshmaur/reddit-scraper` actor id `9sHOY9RzPYGjmTHo8`.

## Exact Working Request Shapes

### Gemini Batch Submit

```json
{
  "batch": {
    "displayName": "voc-classification",
    "inputConfig": {
      "requests": {
        "requests": [
          {
            "request": {
              "contents": [
                {
                  "parts": [
                    {
                      "text": "<classification prompt for one internal batch>"
                    }
                  ]
                }
              ],
              "generationConfig": {
                "responseMimeType": "application/json"
              }
            },
            "metadata": {
              "key": "batch-0",
              "batch_index": 0
            }
          }
        ]
      }
    }
  }
}
```

- Submit path now works. Live operation names:
  - Paytm: `batches/k9wkdw9ygregwlx5jsdg01hvenlsskw9mcmk`.
  - Pronto: `batches/ou7oyrd69xk3snpserf9dngnkzyvs15kn7bm`.
- Both live jobs were still pending after the bounded 300 second poll window, so the gateway used synchronous fallback.
- Sync fallback completed all batches with `quarantined = false`.
- Recommendation for scale: keep the working Batch submit path, but use a longer async worker wait/poll cycle when the operator wants Batch-first overnight throughput instead of the current 5 minute fallback.

### Gemini Sync Fallback

- Endpoint: `models/gemini-3.1-flash-lite:generateContent`.
- Global limiter: 13 RPM.
- Retry behavior: exponential backoff with jitter on 429/503, 3 attempts inside `classify_batch`, quarantine only after final failure.
- Final live result: no sync batches quarantined.

### Reddit Apify Actor

```json
{
  "searchPosts": true,
  "searchComments": false,
  "searchCommunities": false,
  "searchTerms": ["<brand_keyword>"],
  "searchSort": "new",
  "searchTime": "all",
  "maxPostsCount": 100,
  "maxCommentsPerPost": 0,
  "crawlCommentsPerPost": false,
  "includeNSFW": false,
  "proxy": {
    "useApifyProxy": true,
    "apifyProxyGroups": ["RESIDENTIAL"]
  }
}
```

- Actor: `harshmaur/reddit-scraper`.
- Actor id: `9sHOY9RzPYGjmTHo8`.
- Runtime memory: `512 MB`.
- Pronto search terms logged: `["pronto"]`.
- Paytm search terms logged: `["paytm"]`.
- Final live result: Reddit returned 100 raw posts for both Pronto and Paytm.

### Places Text Search and Maps Reviews

```json
{
  "method": "POST",
  "url": "https://places.googleapis.com/v1/places:searchText",
  "headers": {
    "Content-Type": "application/json",
    "X-Goog-Api-Key": "<GOOGLE_MAPS_API_KEY>",
    "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.rating,places.userRatingCount"
  },
  "body": {
    "textQuery": "<brand> <city>"
  }
}
```

- Pronto Places query logged: `withpronto Mumbai`.
- Accepted place:
  - id: `ChIJJ6VMMwDJ5zsR-Ge8ClzxdwA`
  - display name: `PRONTO`
  - address: `55, Corporate Avenue, Tunga Village, Chandivali, Andheri East, Mumbai, Maharashtra 400072, India`
  - Google rating: `1.4`
  - Google user rating count: `87`
- Maps review actor: `compass/google-maps-reviews-scraper`.
- Final live result: Maps returned 86 raw reviews for the accepted Pronto place id.
- Guardrail kept: if Places returns no accepted brand match, the worker does not scrape generic name matches.

## Ingestion Decisions

- Google Play is OSS-primary through `facundoolano/google-play-scraper` version `10.0.0`.
- Play fetches both `lang = "hi"` and `lang = "en"`, `country = "in"`, newest-first, then merges and dedups.
- App Store is OSS-primary through `facundoolano/app-store-scraper` version `0.18.0`.
- App Store page count remains capped by the library behavior; observed live caps were 488 for Pronto and 500 for Paytm.
- Apify store fallbacks remain configured:
  - Play fallback: `neatrat/google-play-store-reviews-scraper`.
  - App Store fallback: `thewolves/appstore-reviews-scraper`.
- MouthShut remains disabled by default: `getdataforme/mouthshut-reviews-scraper`, version marker `disabled-by-default`.

## Live Verification: Pronto

- Run ID: `d108c265-4e9e-4c27-8125-0db0c1cc90e0`.
- Results URL: `https://frontend-eight-sandy-65.vercel.app/runs/d108c265-4e9e-4c27-8125-0db0c1cc90e0`.
- Backend results: `https://voc-ai-agent-api.onrender.com/api/runs/d108c265-4e9e-4c27-8125-0db0c1cc90e0/results`.
- Status: `done`.
- Wall-clock: `778.5` seconds.
- Cost estimate: `$0.2496`.
- Raw source counts: Play `1804`, App Store `488`, Reddit `100`, Maps `86`, MouthShut `0`.
- Stored rows after dedup: Play `982`, App Store `450`, Reddit `92`, Maps `82`.
- Dedup ratio: `0.3519`.
- Quarantine rate: `0.0`.
- Hindi/Hinglish/non-ASCII rows: `472`.
- Downloads verified HTTP 200: CSV, JSON, XLSX.
- Deck-spec endpoint verified HTTP 200.
- Specific sample themes:
  - Complaint: `no-show_of_service_professionals`, `unresponsive_or_non-existent_customer_support`, `unfair_refund_policies_and_failure_to_process_refunds`, `lack_of_accountability_for_service_cancellations`, `significant_delays_in_service_arrival`.
  - Feature request: `ability_to_rebook_the_same_professional_for_consistency`, `functionality_to_modify_or_delete_incorrect_service_addresses`, `option_to_choose_or_filter_preferred_service_partners`, `integration_for_cafe/business_cleaning_services`, `facility_to_add_cleaners_or_service_providers_in_underserved_areas`.
  - Praise: `overall_amazing_customer_experience`, `app_efficiency_and_usability`, `high_quality,_thorough,_and_spotless_cleaning_results`, `professionalism_and_politeness_of_assigned_staff`, `friendly_and_hard-working_nature_of_staff`.

## Live Verification: Paytm

- Run ID: `8b1174a5-096d-4b73-b26b-89723d6245e0`.
- Results URL: `https://frontend-eight-sandy-65.vercel.app/runs/8b1174a5-096d-4b73-b26b-89723d6245e0`.
- Backend results: `https://voc-ai-agent-api.onrender.com/api/runs/8b1174a5-096d-4b73-b26b-89723d6245e0/results`.
- Status: `done`.
- Wall-clock: `884.0` seconds.
- Cost estimate: `$0.3622`.
- Raw source counts: Play `3000`, App Store `500`, Reddit `100`, Maps `0`, MouthShut `0`.
- Stored rows after dedup: Play `1506`, App Store `489`, Reddit `93`.
- Dedup ratio: `0.42`.
- Quarantine rate: `0.0`.
- Hindi/Hinglish/non-ASCII rows: `920`.
- Downloads verified HTTP 200: CSV, JSON, XLSX.
- Deck-spec endpoint verified HTTP 200.
- Specific sample themes:
  - Complaint: `transaction_failures_and_stuck_payments`, `poor_customer_support_and_ineffective_bots`, `device_environment_error/login_issues`, `app_crashes_and_performance_lag`, `refund_and_cashback_delays`.
  - Feature request: `implementation_of_a_system-wide_dark_mode`, `better_organization_of_history_and_filter_options`, `chat_option_for_direct_payment_support`, `option_to_control_screen_brightness_during_scanning`, `customizable_home_screen_and_widget_controls`.
  - Praise: `seamless_and_fast_transaction_processing`, `excellent_ui/ux_design`, `ease_of_use_for_beginners`, `reliable_and_secure_payment_experience`, `uniqueness_compared_to_other_upi_apps`.

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
  "bucket_accuracy": 1.0,
  "severity_accuracy": 0.9,
  "per_class_accuracy": {
    "complaint": 1.0,
    "feature_request": 1.0,
    "praise": 1.0
  },
  "weighted_score": 0.975,
  "provider": "gemini",
  "model": "gemini-3.1-flash-lite",
  "dev_fallback": false
}
```

## Tests

```bash
cd backend
.venv/bin/pytest -q
```

Result: `15 passed in 3.20s`.

## Requirement Coverage

- `quarantine_rate < 0.05`: passed for Pronto (`0.0`) and Paytm (`0.0`).
- Themes are specific, not collapsed to `other`: passed. Both runs still contain residual `other` rows, but each bucket has specific discovered themes with counts and scores.
- Reddit returns posts: passed. Pronto and Paytm each returned 100 raw Reddit posts.
- Maps returns correct Pronto reviews: passed. Places accepted `PRONTO` place id `ChIJJ6VMMwDJ5zsR-Ge8ClzxdwA`; Maps returned 86 raw reviews.
- `DECISIONS.md` updated: completed in this file.
- Carry-forward behavior preserved: partial-source completeness tracking, budget cap, run logs, downloads, deck-spec, admin-configured settings, two-pass themes, low-confidence gate, per-batch LLM progress logs.

## Notes

- Batch submit is now correctly shaped and accepted, but current production behavior falls back to sync after a 300 second Batch poll timeout. This is intentional for interactive completion. For overnight Batch-first operation, increase the poll window or move Batch polling to a durable async job.
- Reddit keyword search can include noisy posts because the actor searches broad Reddit content for the brand term. The v5 requirement was to return real posts and log the exact search terms; deeper relevance filtering can be a v6 improvement.
- Secrets remain in deployment environment variables only and are not committed in this file.

## Final Sprint: Low-Cost Operator Mode

Date: 2026-06-13.

Production URLs:

- Frontend: `https://frontend-eight-sandy-65.vercel.app`.
- Backend: `https://voc-ai-agent-api.onrender.com`.

Final implementation decisions:

- Classification/final analysis now uses only 1/2/3-star rows from Play, App Store, and Maps. Reddit remains optional and unstarred, so it is included only when explicitly enabled.
- Google Maps remains opt-in, searches within India via Places API New, then scrapes Apify reviews sorted lowest-rated first with a 100-review cap.
- Reddit is optional in the submission UI and defaults off.
- MouthShut remains disabled by default.
- The admin panel was removed from the frontend. Settings APIs remain in the backend for future controlled configuration.
- Gemini classification uses the slim compact output contract: `[row_id, bucket, theme]`. The live FirstClub run stored `severity = null` and `english_gloss = null` on newly classified rows.
- Theme labels are display-humanized for charts, tables, and deck-spec output while raw stored themes remain available for filtering and exports.
- Dashboard active runs are capped at 10 visible cards. Run history is capped at 250 API rows and paginated in the UI. Tagged reviews are server-paginated with global column search plus source/rating/bucket/theme filters.
- Cost display now shows sub-rupee values instead of rounding them to `INR 0`.

FirstClub E2E verification:

- Submitted through the production UI.
- Run ID: `1f5938c1-2355-4313-aace-27c0980d63e2`.
- Results URL: `https://frontend-eight-sandy-65.vercel.app/runs/1f5938c1-2355-4313-aace-27c0980d63e2`.
- Status: `done`.
- Cost estimate: `$0.0049`, displayed as about `INR 0.49` at the project conversion rule of INR 100/USD.
- Quarantine rate: `0.0`.
- Gemini tokens: `19,352`.
- Source completeness: Play OSS ok with `958` raw rows; App Store OSS ok with `0` rows; Maps disabled; Reddit disabled; MouthShut disabled.
- Selected/analyzed rows: `162`.
- Rating distribution: 1-star `121`, 2-star `17`, 3-star `24`; no 4/5-star rows were analyzed.
- Review pagination verified: page 2 of 4 returns 50 rows.
- Review search verified: query `refund` returns 17 rows and resets to page 1 of 1.
- Downloads verified HTTP 200: CSV, JSON, XLSX.
- Deck-spec verified with corrected human label: `Pricing: overpriced products compared to competitors.`

Final verification commands:

```bash
backend/.venv/bin/python -m pytest -q
npm --prefix frontend run build
curl -sS https://voc-ai-agent-api.onrender.com/health
```

Final results:

- Backend tests: `26 passed`.
- Frontend build: passed.
- Backend health: `{"ok":true,"bootstrap_ready":true}`.
