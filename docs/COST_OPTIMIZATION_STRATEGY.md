# VoC Platform Cost And Source-Value Strategy

Date: 2026-06-12

## Executive Recommendation

Do not move the production platform back to Gemini free tier. Keep paid Tier 1 / prepaid enabled, run Gemini in Batch-only mode by default, and control cost with per-run caps plus source gating.

The reason is simple: the actual Gemini Batch cost per company is small compared with the cost of bad ingestion and duplicated runs. Moving back to free tier may save a few rupees per company, but it reintroduces throttling, lower reliability, and free-tier data-use tradeoffs. For an overnight workload of 10 companies in 8 hours, the effective strategy is:

1. Default source set: Play Store OSS + App Store OSS + Gemini Batch.
2. Reddit off by default unless it passes a relevance gate.
3. Maps opt-in only for companies with a real physical/service footprint.
4. Batch-only, no 5-minute Batch-to-sync fallback unless the Batch job is cancelled or confirmed dead.
5. Enforce per-company budget tiers in product settings.

## Pricing Primitives

### Gemini

Official Gemini pricing for `gemini-3.1-flash-lite`:

- Standard/sync: input `$0.25 / 1M`, output `$1.50 / 1M`.
- Batch: input `$0.125 / 1M`, output `$0.75 / 1M`.
- Batch is therefore approximately half the token price of sync.

Billing/tier behavior:

- Free tier exists, but has lower limits.
- Tier 1 qualification is linking an active billing account.
- Paid tiers give higher limits and paid-service data privacy behavior.
- Prepay/postpay billing can have delayed processing, and long-running Batch jobs can slightly overrun caps before billing catches up.

Sources:

- Gemini pricing: https://ai.google.dev/gemini-api/docs/pricing
- Gemini billing: https://ai.google.dev/gemini-api/docs/billing

### Google Maps / Places API

Our Maps flow uses Places API (New) only for entity discovery, not review volume. Review volume comes from Apify's Google Maps reviews actor.

Why the screenshot shows Google Maps usage but no cost:

- Places API Text Search Essentials (IDs Only) has an unlimited free usage cap.
- Places API Text Search Pro has a 5,000 monthly free usage cap, then `$32 / 1,000` events at the first paid tier.
- Your screenshot shows only 61 Places API (New) requests, so even if we triggered Pro fields, it is still inside the free cap.

Recommendation: for production discovery, use an IDs-only field mask when possible: `places.id`. If we need `displayName`, `formattedAddress`, `rating`, or `userRatingCount` for audit/debugging, keep it because 10 companies overnight is nowhere near 5,000 calls, but record that it may be a Pro SKU.

Source:

- Google Maps pricing list: https://developers.google.com/maps/billing-and-pricing/pricing

### Apify

Apify Store actors can charge by pay-per-event. The event type and price are defined by each actor author, and the Apify console/invoice is the source of truth.

From your screenshot, current-period Apify usage is `$1.79`, mostly:

| Item | Events | Unit | Cost |
|---|---:|---:|---:|
| Reddit result saved | 532 | `$0.002` | `$1.06` |
| Reddit actor start | 8 | `$0.02` | `$0.16` |
| Google Maps scraped review | 806 | `$0.0006` | `$0.48` |
| Google Maps actor start | 12 | `$0.00005` | `$0.00` |
| Google Play Apify fallback review | 500 | `$0.00015` | `$0.08` |
| App Store Apify fallback review | 10 | `$0.0001` | `$0.00` |

The key insight: this `$1.79` was dominated by repeated test runs and Reddit. It is not the steady-state cost of one clean production run.

Source:

- Apify Store actor pricing models: https://docs.apify.com/platform/actors/running/actors-in-store

## Live Run Evidence

### Latest Done Runs

| Company | Reviews | Sources | Hi/Hinglish rows | Gemini input | Gemini output | Batch-estimated Gemini cost |
|---|---:|---|---:|---:|---:|---:|
| Pronto | 1,606 | Play 982, App Store 450, Reddit 92, Maps 82 | 131 | 288,146 | 184,555 | `$0.1744` |
| Paytm | 2,088 | Play 1,506, App Store 489, Reddit 93 | 539 | 272,390 | 231,780 | `$0.2079` |

The app's older run logs under-reported Gemini cost because they were written before token-priced accounting was fixed. The correct way to model cost is from input/output token counts.

Observed token density:

- Pronto: `294 total tokens / review`.
- Paytm: `242 total tokens / review`.
- Blended planning assumption: `260 total tokens / review`, around `150 input + 110 output`.
- Batch blended cost per review: roughly `$0.00010`.

### Source Value: Pronto

Play/App Store:

- Strong signal.
- Direct product/service feedback.
- Enough praise and complaint data.
- Hindi/Hinglish present.

Maps:

- Strong signal for Pronto.
- 82 reviews, 76 complaints.
- Longer, incident-style reviews.
- Themes included no-show professionals, refund failure, support failure, incomplete cleaning, and service cancellation accountability.
- Recommendation: keep Maps opt-in for Pronto-like service brands.

Reddit:

- Weak/negative signal in the current query.
- 92 posts, all classified as `other`.
- Samples were Spanish/Portuguese/generic and unrelated.
- It polluted the theme chart by pushing `complaint/other` to the top.
- Recommendation: disable Reddit for Pronto unless a relevance gate finds at least 20 clearly relevant India/service posts.

### Source Value: Paytm

Play/App Store:

- Strong signal.
- 1,995 store reviews.
- Rich Hindi/Hinglish coverage.
- Themes were transaction failures, support bots, login/device errors, crashes, refund/cashback delays, charges.

Reddit:

- Low-to-medium signal but currently too noisy.
- 93 posts.
- 75 were `other`.
- Some useful posts did map to transaction failures, compatibility issues, charges, and crashes.
- Recommendation: keep Reddit as opt-in or gated for large fintech/consumer brands, but query and filter more tightly.

Maps:

- Correctly disabled for Paytm.
- Recommendation: keep Maps off for purely digital brands unless we are explicitly studying physical branches or merchant/offline service points.

## Three-Tier Financial Model

Assumptions:

- Gemini uses Batch-only.
- Play/App Store use OSS libraries: no Apify cost.
- Batch cost uses observed blended token density, around `$0.00010 / review`.
- Google Places discovery remains free at this scale.
- INR conversion for planning: `1 USD ~= INR 83`, before tax/FX effects.

### Tier A: Commit / Core

Use this as the default promise.

| Component | Assumption |
|---|---|
| Play/App Store | Up to 2,000 cleaned reviews/company |
| Reddit | Off |
| Maps | Off by default |
| Gemini | Batch-only |

Expected cost:

| Scope | USD | INR approx |
|---|---:|---:|
| Per company | `$0.20 - $0.30` | `INR 17 - 25` |
| 10 companies overnight | `$2 - $3` | `INR 166 - 249` |

This gives enough signal for most app-first companies and keeps the pipeline clean.

### Tier B: Stretch / Signal-Enhanced

Use this when extra channels are likely to add differentiated signal.

| Component | Assumption |
|---|---|
| Play/App Store | Up to 3,000 cleaned reviews/company |
| Reddit | 30-50 relevant posts after relevance filtering |
| Maps | 100-250 reviews only for physical/service brands |
| Gemini | Batch-only |

Expected cost:

| Scope | USD | INR approx |
|---|---:|---:|
| Per company | `$0.45 - $0.85` | `INR 37 - 71` |
| 10 companies overnight | `$4.50 - $8.50` | `INR 374 - 706` |

This is the best practical balance for serious research. It spends when the data source has a chance to change the answer.

### Tier C: Maximum / Exhaustive

Use only when quality is worth extra noise and spend.

| Component | Assumption |
|---|---|
| Play/App Store | Up to 6,000 cleaned reviews/company, 3,000 per app |
| Reddit | 100 posts/company |
| Maps | Up to 1,000 reviews for service/location brands |
| Gemini | Batch-only |

Expected cost:

| Scope | USD | INR approx |
|---|---:|---:|
| Per company | `$1.60 - $2.00` | `INR 133 - 166` |
| 10 companies overnight | `$16 - $20` | `INR 1,328 - 1,660` |

This is still not expensive in absolute terms, but it will produce more noise unless Reddit and Maps are gated.

## Eight-Hour / Ten-Company Operating Plan

Use Batch-only with durable operation tracking:

1. Scrape all companies in parallel.
2. Dedup and incremental-skip previously classified reviews.
3. Submit Gemini Batch jobs per company.
4. Poll for up to the whole overnight window.
5. Do not fall back to sync unless the operator explicitly chooses "finish now".
6. If a Batch job is still pending at 8 hours, show pending classification state instead of spending sync dollars on duplicate work.

Expected throughput:

- 10 companies with 2,000-3,000 reviews each means roughly 20,000-30,000 reviews.
- At observed token density, that is roughly 5.2M-7.8M total tokens.
- Batch Gemini cost is roughly `$2.00-$3.50` for classification at Tier A/B store-heavy volumes.
- The real cost swing comes from Apify Reddit/Maps, not Gemini.

## How To Reduce Cost Without Reducing Output Quality

### Gemini

Keep:

- Paid Tier 1.
- Batch-only.
- `gemini-3.1-flash-lite`.
- Incremental skip.

Change:

- Remove automatic 5-minute Batch-to-sync fallback for production.
- Cap `english_gloss` length to 20-30 words.
- Keep compact JSON keys.
- Track Batch operation IDs and actual token-priced cost per run.
- Use a per-run budget cap that forecasts remaining token cost before each batch.

Do not:

- Move production to free tier.
- Use sync for overnight jobs.
- Let Batch and sync classify the same reviews unless Batch is cancelled.

### Reddit

Current state: too noisy.

Cost from screenshot:

- 100 saved posts costs about `$0.20`.
- Actor start costs `$0.02`.
- So each broad 100-post Reddit pull is about `$0.22` before Gemini processes it.

Quality from live data:

- Pronto: poor. Disable.
- Paytm: mixed. Some useful signal, but too much unrelated content.

Recommendation:

1. Default Reddit off.
2. Add a pre-classification relevance gate.
3. Only keep posts matching brand + product context.
4. Cap at 30-50 relevant posts, not 100 raw posts.
5. Store `reddit_relevance_rate`; if below 30%, mark source low-value and exclude from scoring.

Suggested query shaping:

- For fintech: brand plus `upi`, `wallet`, `refund`, `payment`, `kyc`, `cashback`, `bank`, `fraud`, `support`.
- For local services: brand plus city and category, for example `Pronto Bangalore cleaning house help`.
- Prefer India subreddits and consumer complaint contexts where possible.

### Google Maps

Current state: valuable only for physical/service brands.

Cost from screenshot:

- Reviews: `$0.0006` each.
- 86 reviews ~= `$0.052`.
- 1,000 reviews ~= `$0.60`.

Quality from live data:

- Pronto: high value, concrete service failures.
- Paytm: Maps off, correct.

Recommendation:

1. Keep Maps off by default.
2. Turn on only for companies with physical/service delivery footprint.
3. Cap at 100-250 reviews for normal runs.
4. Use up to 1,000 only for deep-dive Tier C.
5. Use Places IDs-only discovery where possible.
6. If Places returns no confident brand match, do not scrape Maps.

### Apify

Current Apify spend was mostly development/test repetition.

To reduce:

1. Keep Play/App Store OSS primary; Apify only fallback.
2. Set actor max charge limits where supported.
3. Cache source fetches per company/run window.
4. Do not re-run Reddit/Maps if a recent source dataset exists.
5. In UI, show "incremental re-run: scrape reused" when cached.
6. For Reddit, charge on relevant posts, not raw posts: fetch 100 only if relevance is high; otherwise stop after 30-50.

## Decision Framework

Use this per company:

| Company type | Default |
|---|---|
| Pure app/fintech/q-commerce | Tier A |
| Large consumer brand with public controversy | Tier B with Reddit gated |
| Local/service/house-help/cleaning/food/service marketplace | Tier B with Maps on |
| Physical store chain / branch-heavy business | Tier B or C with Maps |
| Early unknown brand | Tier A first, escalate only if source quality is weak |

## Final Take

The optimal platform is not the cheapest one; it is the one that spends only on sources that change the answer.

For 10 companies overnight, my recommended operating mode is Tier B with strict source gates:

- Gemini paid Batch-only.
- Store reviews always.
- Reddit gated and usually capped at 30-50 relevant posts.
- Maps opt-in and capped at 100-250 reviews.

Expected total for 10 companies: about `$5-$9` in a realistic signal-enhanced run, excluding taxes/FX. Tier A can be closer to `$2-$3`. Tier C can reach `$16-$20`, but should be reserved for deep dives because Reddit and Maps can add noise as well as insight.

