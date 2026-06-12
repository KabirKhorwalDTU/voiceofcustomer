# VoC Platform Cost Optimization Strategy

Date: 2026-06-12

This document is the pricing and source-value model for the Voice-of-Customer platform. It is written from first principles and then checked against the live Pronto, Paytm, and Snabbit runs.

## 1. Decision Summary

### Recommendation

Keep Gemini billing enabled. Do not move production back to the free tier.

Run production jobs as Gemini Batch-only. Do not use sync fallback for overnight jobs. The backend now enforces this for Gemini classification and theme discovery.

The cost problem is not Gemini Batch. The cost problem is un-gated paid ingestion, especially Reddit, plus repeated test runs.

### Default Production Policy

| Area | Decision | Why |
|---|---|---|
| Gemini tier | Paid Tier 1 / prepaid | Reliable Batch usage, higher limits, production privacy posture |
| Gemini execution | Batch-only | Roughly 50% of sync token price |
| Sync fallback | Off for production | Prevents duplicate Batch + sync billing |
| Play Store | OSS primary, paid Apify fallback disabled | No paid ingestion cost and no surprise fallback spend |
| App Store | OSS primary, paid Apify fallback disabled | No paid ingestion cost and no surprise fallback spend |
| Reddit | Gated opt-in | High cost and variable relevance |
| Google Maps reviews | Opt-in for physical/service brands | Cheap per review, useful for service failures |
| MouthShut | Disabled | Low reliability / niche source |
| Per-run cap | Keep, but actor-priced | Budget must reflect actual actor economics |

## 2. First-Principles Cost Formula

For one company:

```text
Total company cost =
  Store ingestion cost
+ Apify source cost
+ Google Places discovery cost
+ Gemini Batch token cost
```

In the current architecture:

```text
Store ingestion cost = $0
```

because Play Store and App Store use OSS libraries as primary.

```text
Gemini Batch cost =
  (input_tokens / 1,000,000 * $0.125)
+ (output_tokens / 1,000,000 * $0.75)
```

```text
Gemini Sync equivalent =
  (input_tokens / 1,000,000 * $0.25)
+ (output_tokens / 1,000,000 * $1.50)
```

Batch is therefore about half of sync for the same prompts and outputs.

## 3. Official Unit Prices Used

### Gemini 3.1 Flash-Lite

| Mode | Input price | Output price | Use case |
|---|---:|---:|---|
| Standard / sync | `$0.25 / 1M tokens` | `$1.50 / 1M tokens` | Interactive/debug |
| Batch | `$0.125 / 1M tokens` | `$0.75 / 1M tokens` | Overnight production |

Source: https://ai.google.dev/gemini-api/docs/pricing

### Apify Actor Pricing From Current Billing Screenshot

| Source | Actor/event | Unit price | Formula |
|---|---|---:|---|
| Reddit | Actor Start | `$0.02 / run` | `0.02` if actor returns results |
| Reddit | Result Saved | `$0.002 / result` | `0.02 + 0.002 * results` |
| Google Maps | Actor Start | `$0.00005 / run` | Small fixed event |
| Google Maps | Scraped review | `$0.0006 / review` | `0.00005 + 0.0006 * reviews` |
| Google Play fallback | Review | `$0.00015 / review` | Only if OSS fails |
| App Store fallback | Review | `$0.0001 / review` | Only if OSS fails |

Important correction: the backend previously used a generic `$0.10 / 1k` estimate for Apify. That under-reported Reddit and Maps. The backend estimator has now been updated to actor-specific event pricing.

### Google Maps / Places API

The platform uses Places API (New) only for entity discovery, not review volume. Review volume comes from Apify Maps.

Your Google Cloud screenshot showed:

| API | Requests | Errors | Avg latency | 99% latency | Cost shown |
|---|---:|---:|---:|---:|---:|
| Places API (New) | 61 | 6 | 136 ms | 260 ms | `$0` |

Why cost is `$0` in the screenshot:

- At this usage level, Places discovery is inside Google Maps free monthly usage / credits.
- The current field mask includes `displayName`, `formattedAddress`, `rating`, and `userRatingCount` for entity resolution and audit logs.
- That is not pure IDs-only usage. Official field pricing marks `id` / `name` as Text Search Essentials (IDs Only), `displayName` / `formattedAddress` as Text Search Pro, and `rating` / `userRatingCount` as Text Search Enterprise.
- So Google Places remains low-risk at 100 companies, but it is not literally free forever if volume climbs above the free monthly allowance.

Source: https://developers.google.com/maps/billing-and-pricing/pricing
Field tiers: https://developers.google.com/maps/documentation/places/web-service/data-fields

## 4. Live Runs: Company Unit Economics

Exchange-rate planning assumption: `1 USD = INR 83`. GST/FX not included unless stated.

### Actual / Modeled Cost Per Company

| Company | Cleaned reviews | Paid ingestion used | Gemini input | Gemini output | Gemini Batch cost | Actual/model Apify cost | Total modeled cost | INR/company | Cost / review |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| Pronto | 1,606 | Reddit 100 raw, Maps 86 raw | 288,146 | 184,555 | `$0.1744` | `$0.2716` | `$0.4461` | `INR 37.03` | `$0.000278` |
| Paytm | 2,088 | Reddit 100 raw | 272,390 | 231,780 | `$0.2079` | `$0.2200` | `$0.4279` | `INR 35.51` | `$0.000205` |
| Snabbit | 1,898 | Reddit 100 raw, Maps 19 raw | 281,467 | 217,074 | `$0.1980` | `$0.2314` | `$0.4294` | `INR 35.64` | `$0.000226` |
| Average | 1,864 | Mixed | 280,668 | 211,136 | `$0.1934` | `$0.2410` | `$0.4345` | `INR 36.06` | `$0.000236` |

### Sync Equivalent

| Company | Batch Gemini cost | Sync equivalent | Saved by Batch |
|---|---:|---:|---:|
| Pronto | `$0.1744` | `$0.3489` | `$0.1744` |
| Paytm | `$0.2079` | `$0.4158` | `$0.2079` |
| Snabbit | `$0.1980` | `$0.3960` | `$0.1980` |
| Average | `$0.1934` | `$0.3869` | `$0.1934` |

Batch is doing exactly what we want: it roughly halves Gemini cost.

### Token Density

| Company | Total Gemini tokens | Tokens / cleaned review | Gemini Batch cost / cleaned review |
|---|---:|---:|---:|
| Pronto | 472,701 | 294.3 | `$0.000109` |
| Paytm | 504,170 | 241.5 | `$0.000100` |
| Snabbit | 498,541 | 262.7 | `$0.000104` |
| Average | 491,804 | 266.2 | `$0.000104` |

Planning shortcut:

```text
Gemini Batch classification cost ~= $0.000104 per cleaned review
```

So:

| Cleaned reviews | Gemini Batch cost |
|---:|---:|
| 1,000 | `$0.10` |
| 2,000 | `$0.21` |
| 3,000 | `$0.31` |
| 6,000 | `$0.62` |

## 5. Snabbit Run: End-To-End Evidence

Run ID: `2c565cae-ac25-40a2-91d5-260a3a269029`

### Snabbit Inputs

| Field | Value |
|---|---|
| Company | Snabbit |
| Website | `https://www.snabbit.com/` |
| Play ID | `com.snabbit.customer` |
| App Store ID | `6575381655` |
| Maps enabled | Yes |
| Maps location hint | `Bangalore India` |
| Model | `gemini-3.1-flash-lite` |
| Execution | Batch-only |

### Snabbit Pipeline Timings

| Stage | Started | Finished / observed | Notes |
|---|---|---|---|
| Run start | 10:06:28 UTC | - | Queued then scraping |
| Scraping complete | 10:06:50 UTC | ~22 sec | 2,136 raw rows |
| Cleaning complete | 10:07:02 UTC | ~12 sec | 1,898 cleaned rows |
| Theme discovery Batch submit | 10:07:07 UTC | - | `voc-theme-discovery` |
| Theme discovery Batch complete | 10:08:09 UTC | ~62 sec | Batch, not sync |
| Classification Batch submit | 10:08:12 UTC | - | 19 internal requests |
| Classification complete | 10:09:52 UTC | ~100 sec | Batch, not sync |
| Run complete | 10:09:55 UTC | ~3m 27s total | 0% quarantine |

### Snabbit Source Counts

| Source | Raw rows | Cleaned rows | Dedup impact / notes |
|---|---:|---:|---|
| Play Store | 1,517 | 1,350 | Strong main source |
| App Store | 500 | 436 | Strong complaint source |
| Reddit | 100 | 96 | Mixed but materially useful |
| Maps | 19 | 16 | Low volume, high relevance |
| MouthShut | 0 | 0 | Disabled |
| Total | 2,136 | 1,898 | 11.14% dedup |

### Snabbit Final Costs

| Component | Unit formula | Quantity | Cost |
|---|---|---:|---:|
| Play Store ingestion | OSS | 1,517 raw | `$0.0000` |
| App Store ingestion | OSS | 500 raw | `$0.0000` |
| Reddit ingestion | `$0.02 + 100 * $0.002` | 100 raw | `$0.2200` |
| Maps review ingestion | `$0.00005 + 19 * $0.0006` | 19 raw | `$0.0114` |
| Google Places discovery | free at current volume | 1 place query | `$0.0000` |
| Gemini Batch | token-priced | 281,467 in / 217,074 out | `$0.1980` |
| Total | - | - | `$0.4294` |

Snabbit unit economics:

| Metric | Value |
|---|---:|
| Total modeled cost | `$0.4294` |
| INR at 83/USD | `INR 35.64` |
| INR with 18% GST rough | `INR 42.05` |
| Cost / cleaned review | `$0.000226` |
| Cost / 1,000 cleaned reviews | `$0.226` |
| Gemini share | 46.1% |
| Apify share | 53.9% |

### Snabbit LLM Verification

| Check | Result |
|---|---|
| Gemini sync calls | `0` |
| Classification path | `batch` |
| Batch sync fallback | `false` |
| Internal classification batches | 19 |
| Quarantine rate | 0% |
| Tagged reviews | 1,898 |

## 6. Source-Value Review

### Source Quality By Company

`Non-other %` means the source produced reviews that landed in a specific discovered theme rather than generic `other`. It is a useful proxy for signal quality.

| Company | Source | Cleaned rows | Non-other % | Avg chars | Value verdict |
|---|---|---:|---:|---:|---|
| Pronto | Play | 982 | 52.4% | 61 | Useful, but many short praise rows |
| Pronto | App Store | 450 | 91.6% | 193 | Very useful |
| Pronto | Reddit | 92 | 0.0% | 2,115 | Bad query/noisy source |
| Pronto | Maps | 82 | 97.6% | 296 | Very useful |
| Paytm | Play | 1,506 | 45.1% | 49 | Useful at scale |
| Paytm | App Store | 489 | 79.6% | 179 | Very useful |
| Paytm | Reddit | 93 | 19.4% | 1,013 | Weak/mixed |
| Snabbit | Play | 1,350 | 73.4% | 179 | Very useful |
| Snabbit | App Store | 436 | 73.9% | 139 | Very useful |
| Snabbit | Reddit | 96 | 58.3% | 734 | Useful but expensive |
| Snabbit | Maps | 16 | 81.2% | 198 | Useful, low volume |

### Reddit Value

| Company | Reddit raw | Reddit cost | Cleaned | Non-other % | Cost / useful themed row | Verdict |
|---|---:|---:|---:|---:|---:|---|
| Pronto | 100 | `$0.2200` | 92 | 0.0% | Not meaningful | Disable for Pronto-like query |
| Paytm | 100 | `$0.2200` | 93 | 19.4% | `$0.0122` | Only use with tighter queries |
| Snabbit | 100 | `$0.2200` | 96 | 58.3% | `$0.0039` | Worth testing, but cap/gate |

Reddit is the most dangerous source economically because it is both expensive and noisy. It should not be default-on.

Better Reddit policy:

| Step | Rule |
|---|---|
| 1 | Run a small relevance probe or query-specific actor run |
| 2 | Require at least 30% brand/product-relevant rows |
| 3 | Cap to 30-50 relevant posts for normal runs |
| 4 | Exclude source from scoring if `other` exceeds 70% |
| 5 | Store `reddit_relevance_rate` and `cost_per_useful_reddit_row` |

### Maps Value

| Company | Maps raw | Maps cost | Cleaned | Non-other % | Cost / useful themed row | Verdict |
|---|---:|---:|---:|---:|---:|---|
| Pronto | 86 | `$0.0516` | 82 | 97.6% | `$0.00065` | Strong yes |
| Paytm | 0 | `$0.0000` | 0 | - | - | Correctly off |
| Snabbit | 19 | `$0.0114` | 16 | 81.2% | `$0.00088` | Yes, but low volume |

Maps is cheap and high-quality when the brand has a physical/service footprint. It should remain opt-in, not global.

## 7. Three-Tier Pricing Model

### Tier A: Commit / Core

This is the default promise for app-first analysis.

| Source | Volume | Cost assumption |
|---|---:|---:|
| Play Store | OSS, newest-first | `$0 ingestion` |
| App Store | OSS, newest-first | `$0 ingestion` |
| Reddit | Off | `$0` |
| Maps | Off | `$0` |
| Gemini Batch | ~2,500 cleaned rows combined | `~$0.26` |

| Metric | Estimate |
|---|---:|
| Cost / company | `$0.20 - $0.35` |
| Cost / 10 companies | `$2.00 - $3.50` |
| INR / 10 companies | `INR 166 - 291` |
| Best for | Fintech, pure apps, q-commerce, first-pass scan |

### Tier B: Signal-Enhanced

This is my recommended production default when source gates are implemented.

| Source | Volume | Cost assumption |
|---|---:|---:|
| Play Store | OSS, newest-first | `$0 ingestion` |
| App Store | OSS, newest-first | `$0 ingestion` |
| Reddit | 30-50 relevant rows | `$0.08 - $0.12` |
| Maps | 100-250 rows for service brands | `$0.06 - $0.15` |
| Gemini Batch | ~3,000-3,500 cleaned rows | `$0.31 - $0.36` |

| Metric | Estimate |
|---|---:|
| Cost / company | `$0.40 - $0.75` |
| Cost / 10 companies | `$4.00 - $7.50` |
| INR / 10 companies | `INR 332 - 623` |
| Best for | Serious research runs, source-gated |

### Tier C: Maximum / Deep Dive

Use only when deeper source coverage is worth extra noise and spend.

| Source | Volume | Cost assumption |
|---|---:|---:|
| Play Store | Up to 3,000 rows | `$0 ingestion` |
| App Store | Up to 3,000 rows | `$0 ingestion` |
| Reddit | 100 raw posts | `$0.22` |
| Maps | Up to 1,000 reviews | `$0.60` |
| Gemini Batch | ~6,000 cleaned rows | `$0.62+` |

| Metric | Estimate |
|---|---:|
| Cost / company | `$1.40 - $2.00` |
| Cost / 10 companies | `$14.00 - $20.00` |
| INR / 10 companies | `INR 1,162 - 1,660` |
| Best for | Deep dives into high-value target companies |

## 8. Eight-Hour / Ten-Company Overnight Plan

### Recommended Flow

| Step | Behavior |
|---|---|
| 1 | Submit 10 companies together |
| 2 | Scrape stores in parallel using OSS |
| 3 | Run source gates for Reddit/Maps |
| 4 | Submit Gemini Batch jobs per company |
| 5 | Poll Batch operations for the full overnight window |
| 6 | Do not run sync unless operator manually chooses "finish now" |
| 7 | Surface per-company unit economics in the UI |

### Expected Cost For 10 Companies

| Scenario | Cost / company | 10-company USD | 10-company INR | Comment |
|---|---:|---:|---:|---|
| Store-only first pass | `$0.20 - $0.35` | `$2.00 - $3.50` | `INR 166 - 291` | Cheapest good output |
| Current ungated Reddit for all | `+$0.22` each | `+$2.20` | `+INR 183` | Often not worth it |
| Service-brand Maps for all | `+$0.06 - $0.15` each | `+$0.60 - $1.50` | `+INR 50 - 125` | Worth it for services |
| Recommended gated Tier B | `$0.40 - $0.75` | `$4.00 - $7.50` | `INR 332 - 623` | Best balance |
| Maximum deep dive | `$1.40 - $2.00` | `$14.00 - $20.00` | `INR 1,162 - 1,660` | Use sparingly |

## 9. Free Tier Decision

### Should We Move Back To Gemini Free Tier?

No, not for production.

| Dimension | Free tier | Paid Batch |
|---|---|---|
| Direct token price | Free within limits | Low, predictable |
| Reliability | Lower limits, prior 429/503 experience | Stable enough for 10-company overnight |
| Batch economics | May be constrained / unreliable for production | Explicit Batch pricing and higher limits |
| Data/privacy posture | Free-tier usage may have different product-improvement handling | Paid tier is the right production posture |
| Operator confidence | Low | High |

The actual average Gemini Batch cost from live runs is about `$0.193 / company`. Saving that is not worth bringing back throttling and reliability risk.

## 10. Changes Already Made

| Change | Status |
|---|---|
| Gemini classification Batch-only | Done |
| Gemini theme discovery Batch-only | Done |
| Removed automatic Batch-to-sync fallback | Done |
| Batch poll window increased to 8 hours | Done |
| Gemini cost tracked from input/output tokens | Done |
| Apify cost estimator updated to actor event pricing | Done |
| Paid Play/App Store Apify fallback disabled by default | Done |
| App Store OSS pagination tied to `max_reviews` instead of defaulting to ~500 | Done |
| Google Maps place matching accepts brand-prefixed location names | Done |
| Google Maps discovery collects all matching place IDs across queries | Done |

## 11. Required Next Product Improvements

### Must Do

| Feature | Reason |
|---|---|
| Add Reddit relevance gate | Prevent Pronto-style noisy Reddit spend |
| Add source-level ROI card | Operator should see cost/useful row |
| Add `llm_mode = batch_only` in admin UI | Make policy visible |
| Add "Batch pending" state | Batch-only should not look stuck |
| Persist Batch operation IDs as first-class fields | Easier cost/debug audit |

### Should Do

| Feature | Reason |
|---|---|
| Add per-source max spend | Stop source overruns before they happen |
| Cache Reddit/Maps datasets by company/date window | Avoid repeated paid actor runs |
| Add source score: relevance %, non-other %, avg severity | Decide source inclusion from data |
| Add Maps cap presets: 100 / 250 / 1000 | Align with Tier A/B/C |

## 12. Final Recommendation

Run the platform as Tier B for serious overnight work:

| Source | Policy |
|---|---|
| Play Store | Always on via OSS |
| App Store | Always on via OSS |
| Gemini | Paid Batch-only |
| Reddit | Gated opt-in, 30-50 relevant posts |
| Maps | Opt-in for services, 100-250 reviews |

For 10 companies in 8 hours, plan for:

```text
Good default budget: $5 - $8 total
Conservative max budget: $20 total
```

That is not "cheap mode"; it is high-output, cost-disciplined mode. The goal is to spend money where it changes the insight, not where a source happens to return rows.

## 13. INR 5,000 / 100-Company Budget Test

Your stated operating budget:

```text
INR 5,000 / 100 companies = INR 50 per company
```

Planning assumptions:

| Variable | Value |
|---|---:|
| USD-INR planning rate | 83 |
| GST / tax buffer | 18% |
| Target all-in cost before tax | `<= INR 42.37` |
| Target all-in cost after tax | `<= INR 50.00` |

Observed corrected live-run average:

| Metric | Value |
|---|---:|
| Average USD / company | `$0.4345` |
| Average INR / company before tax | `INR 36.06` |
| Average INR / company with 18% buffer | `INR 42.55` |
| 100-company cost before tax | `INR 3,606` |
| 100-company cost with 18% buffer | `INR 4,255` |

Conclusion: the current Batch-only system fits the INR 5,000 / 100-company budget, but only narrowly if Reddit and Maps are allowed to run without gates. The budget is safe for Tier A and disciplined Tier B. It is not safe for maximum Maps + Reddit on every company.

### Budget Stress Test

| Scenario | Per-company USD | Per-company INR before tax | Per-company INR with 18% buffer | 100-company INR with buffer | Budget fit |
|---|---:|---:|---:|---:|---|
| Store-only, ~2,500 cleaned rows | `$0.26` | `INR 21.58` | `INR 25.46` | `INR 2,546` | Safe |
| Live average: stores + Reddit 100 + selective Maps | `$0.4345` | `INR 36.06` | `INR 42.55` | `INR 4,255` | Safe but watch |
| Stores + Reddit 100 for every company | `$0.48 - $0.60` | `INR 40 - 50` | `INR 47 - 59` | `INR 4,700 - 5,900` | Risky |
| Stores + Reddit 100 + Maps 250 for every company | `$0.63 - $0.85` | `INR 52 - 71` | `INR 62 - 83` | `INR 6,200 - 8,300` | Not safe |
| Deep dive: 6,000 cleaned rows + Reddit 100 + Maps 1,000 | `$1.40 - $2.00` | `INR 116 - 166` | `INR 137 - 196` | `INR 13,700 - 19,600` | Not for bulk |

Operating rule:

| Run type | Hard cap |
|---|---:|
| Bulk outreach / 100 companies | `INR 45 - 50/company` |
| Serious shortlisted research | `INR 75/company` |
| Deep dive / one-off PM case study | `INR 150 - 200/company` |

## 14. What Creates Gemini Tokens

Gemini is billed on tokens, not API calls. A token is a chunk of text in the prompt or response. In this platform, both the instructions and every review row become tokens.

### Input Token Sources

| Input component | Why it exists | Cost behavior |
|---|---|---|
| System/task instructions | Tells Gemini to classify VoC rows and obey schema | Repeated in every batch |
| Bucket definitions | Complaint / feature_request / praise | Repeated in every batch |
| Severity rubric | Defines severity 1/2/3 | Repeated in every batch |
| Frozen theme set | Forces assignment to company-specific themes | Repeated in every classification batch |
| Review rows | `review_hash`, source, rating, date, text | Scales with review count and review length |
| JSON schema instructions | Keeps parseable output | Repeated in every batch |
| Theme discovery sample | Up to ~300 reviews | One-time per run |

### Output Token Sources

| Output component | Why output is high |
|---|---|
| `review_hash` | Returned for every review so tags map back exactly |
| `language` | Returned for every review |
| `english_gloss` | Biggest driver: every Hindi/Hinglish/English review gets a gloss/summary |
| `bucket` | Returned for every review |
| `theme` | Returned for every review; long theme names multiply cost |
| `severity` | Returned for every review |
| JSON keys and punctuation | Repeated for every object in every batch |

Output tokens are expensive because Gemini Flash-Lite Batch output is `$0.75 / 1M`, while Batch input is `$0.125 / 1M`. Output is 6x the input unit price. That is why compacting output matters more than compacting the prompt.

### Live Token Shape

| Company | Input tokens | Output tokens | Output share | Cost implication |
|---|---:|---:|---:|---|
| Pronto | 288,146 | 184,555 | 39.0% | Output is 79% of Gemini bill |
| Paytm | 272,390 | 231,780 | 46.0% | Output is 84% of Gemini bill |
| Snabbit | 281,467 | 217,074 | 43.5% | Output is 82% of Gemini bill |

Formula example for Snabbit:

```text
Input cost  = 281,467 / 1,000,000 * $0.125 = $0.0352
Output cost = 217,074 / 1,000,000 * $0.75  = $0.1628
Total       = $0.1980
```

### Why "900 API requests" Does Not Equal the App Cost

The Google AI Studio usage dashboard counts provider-level requests across all tests, probes, Batch operations, evals, and reruns. The platform run cost is computed from per-run token usage recorded in the database. A single Batch run can contain many internal generation requests, and Google may count those separately in usage dashboards.

For cost governance, trust this order:

| Source of truth | Use it for |
|---|---|
| `runs.cost_estimate` | User-facing per-run total |
| `runs.completeness.*.cost_usd` | Per-source ingestion cost |
| Gemini run logs token counts | Per-run LLM cost |
| Google AI Studio global usage | Account-level reconciliation, not per-company attribution |

## 15. What We Send And What We Receive

### Theme Discovery Input

One Batch request contains a prompt that is structurally like:

```json
{
  "task": "Discover customer review themes",
  "buckets": ["complaint", "feature_request", "praise"],
  "rules": {
    "max_themes_per_bucket": 10,
    "language": "Hindi/Hinglish/English allowed",
    "output": "strict JSON"
  },
  "sample_reviews": [
    {
      "review_hash": "abc123",
      "source": "play",
      "rating": 1,
      "date": "2026-06-11",
      "text": "Paise debit ho gaye but service nahi mila"
    }
  ]
}
```

### Theme Discovery Output

```json
{
  "complaint": [
    "payment_failures",
    "poor_customer_support",
    "refund_delays",
    "other"
  ],
  "feature_request": [
    "better_slot_availability",
    "faster_refunds",
    "other"
  ],
  "praise": [
    "fast_service",
    "easy_booking",
    "other"
  ]
}
```

### Classification Input

Each internal Batch request classifies about 100 reviews:

```json
{
  "task": "Classify each review into the frozen theme set",
  "severity_scale": {
    "1": "cosmetic/minor",
    "2": "blocks a task, workaround exists",
    "3": "churn, money lost, trust or safety broken"
  },
  "theme_set": {
    "complaint": ["payment_failures", "poor_customer_support", "other"],
    "feature_request": ["faster_refunds", "other"],
    "praise": ["easy_booking", "other"]
  },
  "reviews": [
    {
      "review_hash": "abc123",
      "source": "play",
      "rating": 1,
      "date": "2026-06-11",
      "text": "Paise debit ho gaye but service nahi mila"
    }
  ],
  "required_output_fields": [
    "review_hash",
    "language",
    "english_gloss",
    "bucket",
    "theme",
    "severity"
  ]
}
```

### Classification Output

```json
[
  {
    "review_hash": "abc123",
    "language": "hinglish",
    "english_gloss": "Money was debited but the service was not delivered.",
    "bucket": "complaint",
    "theme": "payment_failures",
    "severity": 3
  }
]
```

This output shape is the main reason output tokens are high. Every cleaned review receives a full JSON object.

### Gemini Batch API Wrapper

The platform wraps those prompts in Google's Batch request shape:

```json
{
  "batch": {
    "displayName": "voc-classify-<run_id>",
    "inputConfig": {
      "requests": {
        "requests": [
          {
            "request": {
              "contents": [
                { "parts": [{ "text": "<classification prompt>" }] }
              ],
              "generationConfig": { "responseMimeType": "application/json" }
            },
            "metadata": { "key": "batch-0" }
          }
        ]
      }
    }
  }
}
```

The response is parsed from `response.inlinedResponses[].response` and then each JSON row is validated before it is inserted into `reviews`.

## 16. Store Fallback And Store Volume Policy

### Paid Fallback Decision

| Question | Answer |
|---|---|
| Should Google Play/App Store paid Apify fallback remain active? | No |
| Should we delete the fallback code entirely? | No |
| Final implementation | Disabled seam via `ENABLE_PAID_STORE_FALLBACK = False` |

Reason: Play and App Store ingestion should be free by default. If OSS fails, the run should mark that source failed/partial rather than silently spend on Apify. The code path remains available for a future explicit "paid rescue mode".

### Why App Store Was Around 500 Rows

The App Store OSS scraper paginates in pages of 50. It previously defaulted to 10 pages:

```text
10 pages * 50 rows = ~500 rows
```

That was an implementation cap, not a business rule. It is now fixed so the page limit follows `max_reviews`.

### Why Play Store Was Around 1,500-2,000 Rows

Play Store is requested in both Hindi and English:

```text
max_reviews = 3,000
per language request ~= 1,500
languages = hi + en
merge + dedup
```

Actual cleaned rows can be lower because:

| Cause | Effect |
|---|---|
| Store/library returns fewer rows than requested | Less raw volume |
| `hi` and `en` overlap | Dedup lowers final count |
| Very short/empty rows removed | Cleaner lowers final count |
| Near-duplicate reviews removed | Cleaner lowers final count |

### Should We Pull More Since OSS Is Free?

Ingestion is free. Classification is not. At the observed average:

```text
1,000 additional cleaned reviews ~= $0.104 Gemini Batch ~= INR 8.63 before tax
```

So more store rows are cheap, but not free. The correct policy is:

| Tier | Store cap | Why |
|---|---:|---|
| Bulk / 100 companies | 2,500-3,000 cleaned rows total target | Fits INR 50/company |
| Serious company run | 3,000-5,000 cleaned rows total target | Better theme stability |
| Deep dive | Up to 6,000 cleaned rows | Use when quality matters more than budget |

Recommendation: keep the configured `max_reviews = 3,000` for now. Do not raise it globally until Reddit and Maps are gated, because the budget headroom is already being consumed by paid sources.

## 17. Google Reviews Execution: Why Snabbit Was Low

The low Snabbit Maps count was not because Google Maps had only 19 reviews. It was a place-resolution guardrail bug.

### What Happened

| Place found by Places API | Review count shown by Places/Maps | Old matcher result | Why |
|---|---:|---|---|
| `Snabbit` | 19 | Accepted | Exact normalized name match |
| `Snabbit Kadubeesanahalli Training Centre` | 114 | Rejected | Extra location words broke exact match |
| `Snabbit Office training centre Mumbai` | 169 | Would be rejected unless queried and substring-allowed | Extra words |
| `Snabbit Training Centre - Goregaon` | 19 | Would be rejected unless queried and substring-allowed | Extra words |

The old code accepted only exact normalized matches like:

```text
snabbit == snabbit
```

It rejected:

```text
snabbitkadubeesanahallitrainingcentre contains snabbit
```

### What Changed

| Change | Effect |
|---|---|
| Place matcher now accepts brand substring matches | `Snabbit Kadubeesanahalli Training Centre` is accepted |
| Discovery now collects all matching places across queries | Multiple Snabbit place IDs can be scraped |
| Guardrail still rejects generic non-brand matches | Avoids scraping wrong `Pronto` / unrelated locations |

### Maps Cost From First Principles

Apify Maps actor cost from billing screenshot:

```text
Maps cost = $0.00005 actor start + $0.0006 * scraped_reviews
```

| Maps reviews scraped | Maps Apify cost | INR before tax |
|---:|---:|---:|
| 19 | `$0.0114` | `INR 0.95` |
| 86 | `$0.0516` | `INR 4.28` |
| 114 | `$0.0685` | `INR 5.69` |
| 250 | `$0.1501` | `INR 12.46` |
| 1,000 | `$0.6001` | `INR 49.81` |

This is the core Maps tradeoff: 100-250 Maps reviews are affordable and often high-signal. 1,000 Maps reviews alone can consume the full INR 50/company budget before Gemini or Reddit.

### Recommended Maps Policy

| Company type | Maps setting | Cap |
|---|---|---:|
| Pure app / fintech wallet | Off | 0 |
| Service marketplace with physical/training/service centers | On | 100-250 |
| Deep dive on a service brand | On | 1,000 |

For Snabbit specifically: Maps should be on, but default cap should be 250 unless we are intentionally doing a deep service-quality audit.

## 18. Secret Safety Check

Question: if someone opens GitHub, can they access the API keys?

Current repo scan result:

| Check | Result |
|---|---|
| Tracked `.env` files | None |
| Env example files | Present, placeholders only |
| Real Apify / Google / GitHub / Render / Supabase tokens in tracked files | Not found |
| Token-like matches | Only redaction regexes and fake test fixtures |
| Runtime secrets location | Render/Vercel/Supabase env, not Git |

So: GitHub users should not be able to access the live API keys from the repository. The keys were exposed in chat earlier, so operationally they should still be rotated, but they are not committed to Git.

## 19. Lowest-Cost High-Output Recommendation

For the next 100 companies, use this exact policy:

| Lever | Setting |
|---|---|
| Gemini | `gemini-3.1-flash-lite`, Batch-only |
| Sync fallback | Off |
| Play Store | OSS on |
| App Store | OSS on |
| Paid Play/App Store fallback | Off |
| Reddit | Off by default; enable only after relevance gate |
| Maps | Off by default; enable for service brands at 100-250 cap |
| Max reviews | 3,000 per store source |
| Per-company budget cap | `$0.55` hard cap for bulk |

Expected 100-company budget under this policy:

| Cost bucket | 100-company expected cost |
|---|---:|
| Gemini Batch | `$25 - $35` |
| Reddit gated | `$0 - $8` |
| Maps gated | `$0 - $10` |
| Google Places discovery | Usually `$0` at this volume, due free allowance/credits |
| Total USD | `$30 - $50` |
| Total INR before tax | `INR 2,490 - 4,150` |
| Total INR with 18% buffer | `INR 2,938 - 4,897` |

This fits the INR 5,000 / 100-company target while preserving the core output quality.
