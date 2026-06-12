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
| Play Store | OSS primary | No paid ingestion cost |
| App Store | OSS primary | No paid ingestion cost |
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

Why cost is `$0`:

- At this usage level, Places discovery is inside Google Maps free monthly usage.
- IDs-only Text Search is free at any volume.
- Text Search Pro has a monthly free cap before paid billing.

Source: https://developers.google.com/maps/billing-and-pricing/pricing

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
| Play Store | Up to 2,000 cleaned rows | `$0 ingestion` |
| App Store | Up to 500 cleaned rows | `$0 ingestion` |
| Reddit | Off | `$0` |
| Maps | Off | `$0` |
| Gemini Batch | ~2,500 cleaned rows | `~$0.26` |

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
| Play Store | Up to 3,000 cleaned rows | `$0 ingestion` |
| App Store | Up to 500 cleaned rows | `$0 ingestion` |
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
