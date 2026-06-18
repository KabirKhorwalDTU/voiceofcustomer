# Voice of Customer Analyst - Product Brief

## One-line Summary

Voice of Customer Analyst is a web platform that turns public customer feedback for consumer apps into ranked product issues, L1/L2 sub-issue maps, raw quote evidence, exports, and deck-ready synthesis.

## Who It Is For

- Founders who want to understand why customers are unhappy before choosing what to fix.
- Product builders researching a company, category, or competitor.
- Operators who need a fast overnight review-mining workflow without manually reading thousands of app-store comments.

## Public Product Flow

1. A user enters only a company name and company website.
2. The backend resolves app-store identifiers and brand keywords.
3. The pipeline collects public feedback from Play Store, App Store, Google Maps reviews, Reddit, and the disabled MouthShut seam.
4. The cleaner keeps low-rated, high-signal reviews and deduplicates repeated text.
5. Gemini Batch creates a dynamic L1/L2 issue taxonomy for that company.
6. Every selected review is tagged to an L1 theme and L2 sub-issue.
7. The company page shows the strongest issues, source mix, quotes, exports, and a deck-spec.

## What We Built

| Area | What exists now |
| --- | --- |
| Public landing page | Explains the product, supported sources, and lets users start with company name + website. |
| Guest workspace | Users can run analyses without logging in; runs are scoped to a browser guest id. |
| Simple auth | Email sign-in stores a user session and claims guest runs into that user's saved workspace. |
| Multi-tenant data model | Companies and runs can belong to either a signed-in user or a guest workspace. |
| Internal operator console | `/kabir` keeps the overnight queue, cost, active run, rerun, and delete controls separate from the public product surface. |
| Source ingestion | Play Store and App Store through OSS scrapers, Google Maps through Places + Apify, Reddit through Apify, MouthShut seam retained but disabled by default. |
| LLM classification | Gemini Batch-based L1/L2 classification with compact prompts and run-level cost logging. |
| Company detail page | Shows run state, source completeness, L1/L2 theme density, charts, source ROI, paginated tagged reviews, downloads, and deck-spec. |
| Exports | JSON, CSV, XLSX tagged-review downloads. |
| Operational logs | Run logs persist provider usage, retry/failure details, source status, costs, and pipeline stages. |

## Technical Architecture

| Layer | Choice | Why it matters |
| --- | --- | --- |
| Frontend | React + Vite on Vercel | Fast static frontend delivery, simple routing, low operational overhead. |
| Backend | FastAPI on Render | Long-running scrape/classify jobs do not fit Vercel serverless timeouts, so the backend needs a persistent service. |
| Worker | In-process sequential worker | Good fit for overnight batches; avoids over-parallelizing paid scrapers and Gemini jobs. |
| Database | Supabase Postgres | Durable run history, review storage, logs, settings, and multi-tenant ownership fields. |
| Scraping | OSS for app stores, Apify for Reddit/Maps | Keeps high-volume store scraping low-cost while retaining paid scrapers for harder public surfaces. |
| LLM | Gemini Batch | Lower request pressure and better cost profile than synchronous calls for thousands of reviews. |

## What This Demonstrates

- Product thinking: narrowed a messy "voice of customer" problem into a repeatable founder-facing workflow.
- Systems design: separated frontend, API, worker, external scrapers, LLM gateway, and database state.
- Cost discipline: built per-run cost tracking, source ROI views, budget caps, and compact Gemini prompts.
- Reliability: partial-source success, run logs, reruns, stale-run recovery, and visible pipeline states.
- Data product UX: moves from raw review volume to ranked L1/L2 themes, evidence quotes, and deck-ready output.
- Productization: added a public landing page, guest trials, login-based saved workspaces, and an internal operator URL.

## Current Boundaries

- Auth is intentionally simple email-session auth, not enterprise-grade identity.
- Billing, team accounts, public documentation, email outreach, deck rendering, and Apollo integrations are intentionally out of scope for this phase.
- MouthShut is listed as a supported seam but remains disabled by default because the live source was unreliable.
- The operator console is separated at `/kabir`; a later production version should protect it with stronger operator auth.

## Best Resume Framing

Built a multi-tenant Voice-of-Customer intelligence platform that ingests public reviews across app stores, Google Maps, Reddit, and review sites, classifies thousands of low-rated reviews through a cost-tracked LLM batch pipeline, and produces product-ready L1/L2 issue maps, quote evidence, exports, and deck specifications.
