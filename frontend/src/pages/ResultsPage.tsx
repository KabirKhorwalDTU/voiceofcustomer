import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Clipboard, Download, ExternalLink, Search } from "lucide-react";
import { ResultsCharts } from "../components/Charts";
import { StatusBadge } from "../components/StatusBadge";
import { api, Results, ReviewPage, RunLog } from "../lib/api";

const ACTIVE = new Set(["queued", "scraping", "classifying"]);

type ReviewFilters = {
  q: string;
  source: string;
  bucket: string;
  theme: string;
  rating: string;
};

const emptyFilters: ReviewFilters = { q: "", source: "", bucket: "", theme: "", rating: "" };

export function ResultsPage() {
  const { runId } = useParams();
  const [results, setResults] = useState<Results | null>(null);
  const [reviewPage, setReviewPage] = useState<ReviewPage | null>(null);
  const [filters, setFilters] = useState<ReviewFilters>(emptyFilters);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");

  async function loadResults() {
    if (!runId) return;
    const next = await api.results(runId);
    setResults(next);
  }

  async function loadReviews(nextPage = page) {
    if (!runId) return;
    const next = await api.reviews(runId, { page: nextPage, page_size: pageSize, ...filters });
    setReviewPage(next);
  }

  useEffect(() => {
    loadResults().catch((err) => setError(err.message));
  }, [runId]);

  useEffect(() => {
    loadReviews().catch((err) => setError(err.message));
  }, [runId, page, pageSize, filters.q, filters.source, filters.bucket, filters.theme, filters.rating]);

  useEffect(() => {
    if (!results || !ACTIVE.has(results.run.status)) return;
    const interval = window.setInterval(() => {
      loadResults().catch(() => undefined);
      loadReviews().catch(() => undefined);
    }, 4000);
    return () => window.clearInterval(interval);
  }, [results?.run.status, runId, page, pageSize, filters]);

  const completeness = Object.entries(results?.run.completeness || {}) as Array<[string, { status: string; count?: number; error?: string; reason?: string }]>;
  const incomplete = completeness.filter(([, value]) => !["ok", "disabled"].includes(value.status));
  const disabled = completeness.filter(([, value]) => value.status === "disabled");
  const lowConfidence = Boolean(results && results.run.quarantine_rate > 0.2);

  const sourceOptions = useMemo(() => Object.keys(results?.summary.source_mix || {}).sort(), [results]);
  const bucketOptions = useMemo(() => Object.keys(results?.summary.bucket_split || {}).sort(), [results]);
  const themeOptions = useMemo(() => (results?.themes || []).map((theme) => theme.theme), [results]);
  const ratingOptions = useMemo(() => Object.keys(results?.summary.rating_distribution || {}).sort(), [results]);

  const geminiUsage = useMemo(() => rollupLogs(results?.logs || [], "gemini"), [results]);
  const apifyUsage = useMemo(() => rollupLogs(results?.logs || [], "apify"), [results]);
  const trackedCost = Math.max(results?.run.cost_estimate || 0, geminiUsage.cost + apifyUsage.cost);

  function updateFilter(key: keyof ReviewFilters, value: string) {
    setPage(1);
    setFilters((current) => ({ ...current, [key]: value }));
  }

  if (error) {
    return <main className="app-shell"><p className="error">{error}</p></main>;
  }

  if (!results) {
    return <main className="app-shell"><div className="empty-slab">Loading run...</div></main>;
  }

  return (
    <main className="app-shell detail-shell">
      <header className="command-header result-header">
        <div>
          <p className="eyebrow">Company Results</p>
          <h1>{results.company.name}</h1>
          <p>{results.run.current_stage} · {results.run.stage_detail || "waiting for next event"}</p>
        </div>
        <div className="header-metrics">
          <StatusBadge status={results.run.status} />
          <Link to="/" className="icon-button" title="Back to dashboard">
            <ArrowLeft size={18} />
          </Link>
        </div>
      </header>

      <section className="run-progress-panel">
        <div>
          <strong>{results.run.current_stage}</strong>
          <span>{Math.round((results.run.progress || 0) * 100)}% complete</span>
        </div>
        <div className="progress-track large">
          <span style={{ width: `${Math.max(3, Math.round((results.run.progress || 0) * 100))}%` }} />
        </div>
      </section>

      {incomplete.length ? (
        <section className="banner warning">
          Partial data: {incomplete.map(([source, value]) => `${source} ${value.status}`).join(", ")}
        </section>
      ) : (
        <section className="banner ok">All configured sources completed.</section>
      )}
      {disabled.length ? <section className="banner muted-banner">Disabled sources: {disabled.map(([source]) => source).join(", ")}</section> : null}
      {lowConfidence ? <section className="banner danger">Low confidence: {Math.round(results.run.quarantine_rate * 100)}% of LLM batches were quarantined.</section> : null}

      <section className="stats-grid results-stats">
        <Metric label="Selected reviews" value={String(results.summary.total_reviews || 0)} note="1/2/3-star rated sources, plus Reddit only if enabled" />
        <Metric label="Date range" value={`${results.summary.date_range?.start || "n/a"} to ${results.summary.date_range?.end || "n/a"}`} />
        <Metric label="Tracked cost" value={`${formatInr(trackedCost)} / ${formatInr(results.run.budget_cap)}`} note={`Gemini ${formatInr(geminiUsage.cost)} · Apify ${formatInr(apifyUsage.cost)}`} />
        <Metric label="Gemini tokens" value={geminiUsage.tokens.toLocaleString("en-IN")} note={`${geminiUsage.calls} logged calls`} />
        <Metric label="Dedup / quarantine" value={`${Math.round(results.run.dedup_ratio * 100)}% / ${Math.round(results.run.quarantine_rate * 100)}%`} />
      </section>

      <ResultsCharts results={results} />

      <section className="section-block">
        <div className="section-title-row">
          <div>
            <h2>Source ROI</h2>
            <p>Useful rows are rows assigned to a non-other theme.</p>
          </div>
        </div>
        <div className="table-wrap compact-table-wrap">
          <table className="command-table compact-table">
            <thead>
              <tr>
                <th>Source</th>
                <th>Rows</th>
                <th>Useful rows</th>
                <th>Non-other %</th>
                <th>Avg rating</th>
                <th>Cost</th>
                <th>Cost/useful row</th>
              </tr>
            </thead>
            <tbody>
              {(results.summary.source_quality || []).map((row: any) => (
                <tr key={row.source}>
                  <td>{row.source}</td>
                  <td>{row.rows}</td>
                  <td>{row.useful_rows}</td>
                  <td>{Math.round((row.non_other_pct || 0) * 100)}%</td>
                  <td>{row.avg_rating ?? "n/a"}</td>
                  <td>{formatInr(row.cost_usd || 0)}</td>
                  <td>{row.cost_per_useful_row == null ? "n/a" : formatInr(row.cost_per_useful_row)}</td>
                </tr>
              ))}
              {!results.summary.source_quality?.length ? (
                <tr><td colSpan={7}>No source quality rows yet.</td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>

      <section className="history-panel">
        <div className="table-toolbar review-toolbar">
          <div>
            <h2>Tagged Reviews</h2>
            <p>{reviewPage?.total || 0} rows · page {reviewPage?.page || 1} of {reviewPage?.pages || 1}</p>
          </div>
          <label className="search-box wide-search">
            <Search size={15} />
            <input value={filters.q} onChange={(event) => updateFilter("q", event.target.value)} placeholder="Search every column..." />
          </label>
          <div className="download-row">
            {(["xlsx", "csv", "json"] as const).map((fmt) => (
              <a className="secondary-button" href={api.downloadUrl(results.run.id, fmt)} key={fmt}>
                <Download size={15} />
                {fmt}
              </a>
            ))}
          </div>
        </div>

        <div className="column-filter-row">
          <Select label="Source" value={filters.source} options={sourceOptions} onChange={(value) => updateFilter("source", value)} />
          <Select label="Rating" value={filters.rating} options={ratingOptions} onChange={(value) => updateFilter("rating", value)} />
          <Select label="Bucket" value={filters.bucket} options={bucketOptions} onChange={(value) => updateFilter("bucket", value)} />
          <Select label="Theme" value={filters.theme} options={themeOptions} display={humanizeTheme} onChange={(value) => updateFilter("theme", value)} />
          <label>
            Rows / page
            <select value={pageSize} onChange={(event) => { setPage(1); setPageSize(Number(event.target.value)); }}>
              {[25, 50, 100].map((size) => <option key={size} value={size}>{size}</option>)}
            </select>
          </label>
        </div>

        <div className="table-wrap command-table-wrap review-table-wrap">
          <table className="command-table review-table">
            <thead>
              <tr>
                <th>Hash</th>
                <th>Source</th>
                <th>Rating</th>
                <th>Date</th>
                <th>Bucket</th>
                <th>Theme</th>
                <th>Review</th>
              </tr>
            </thead>
            <tbody>
              {(reviewPage?.items || []).map((review) => (
                <tr key={review.id} className={review.representative_flag ? "representative" : ""}>
                  <td className="mono">{review.review_hash.slice(0, 8)}</td>
                  <td>{review.source}</td>
                  <td>{review.rating ?? "n/a"}</td>
                  <td>{review.date || "n/a"}</td>
                  <td>{review.bucket || "pending"}</td>
                  <td>{humanizeTheme(review.theme)}</td>
                  <td className="review-text">{review.text}</td>
                </tr>
              ))}
              {!reviewPage?.items?.length ? (
                <tr><td colSpan={7}>No reviews match these filters.</td></tr>
              ) : null}
            </tbody>
          </table>
        </div>

        <div className="pagination-row">
          <button className="secondary-button" disabled={page <= 1} onClick={() => setPage(1)}>First</button>
          <button className="secondary-button" disabled={page <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>Previous</button>
          <span>Page {reviewPage?.page || page} of {reviewPage?.pages || 1}</span>
          <button className="secondary-button" disabled={!reviewPage || page >= reviewPage.pages} onClick={() => setPage((value) => value + 1)}>Next</button>
        </div>
      </section>

      <section className="deck-grid">
        <div className="section-block deck-panel">
          <div className="section-title-row">
            <div>
              <h2>Deck Spec</h2>
              <p>Humanized themes, ready for the post-v1 deck generator.</p>
            </div>
            <button
              className="secondary-button"
              onClick={async () => {
                await navigator.clipboard.writeText(results.deck_spec);
                setCopied(true);
              }}
            >
              <Clipboard size={15} />
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
          <pre className="deck-spec">{results.deck_spec}</pre>
        </div>
        <div className="section-block stub-panel">
          <h2>Deck API stub</h2>
          <p>Chronicle / Gamma handoff target is reserved for the next phase.</p>
          <button className="secondary-button" disabled>
            <ExternalLink size={15} />
            Send later
          </button>
        </div>
      </section>
    </main>
  );
}

function Metric({ label, value, note = "" }: { label: string; value: string; note?: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
      {note ? <small>{note}</small> : null}
    </div>
  );
}

function Select({ label, value, options, display, onChange }: { label: string; value: string; options: string[]; display?: (value: string) => string; onChange: (value: string) => void }) {
  return (
    <label>
      {label}
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">All</option>
        {options.map((option) => (
          <option value={option} key={option}>{display ? display(option) : option}</option>
        ))}
      </select>
    </label>
  );
}

function rollupLogs(logs: RunLog[], provider: "gemini" | "apify") {
  return logs
    .filter((log) => log.provider === provider)
    .reduce(
      (totals, log) => ({
        calls: totals.calls + Number((log.details?.calls as number | undefined) || (log.provider === "gemini" && log.total_tokens > 0 ? 1 : 0)),
        cost: totals.cost + Number(log.cost_usd || 0),
        tokens: totals.tokens + Number(log.total_tokens || 0),
      }),
      { calls: 0, cost: 0, tokens: 0 },
    );
}

function humanizeTheme(theme?: string | null) {
  if (!theme) return "Pending";
  if (theme === "other") return "Other";
  if (theme === "payments_or_refunds") return "Payments & refunds.";
  if (theme === "unfair_refund_policies_and_failure_to_process_refunds") {
    return "Refunds: unfair policies & failures to process.";
  }
  const words = theme.replaceAll("_", " ").trim();
  const prefixes: Record<string, string> = {
    refund: "Refunds",
    payment: "Payments",
    booking: "Bookings",
    login: "Login",
    support: "Support",
    delivery: "Delivery",
    quality: "Quality",
    app: "App",
    order: "Orders",
    pricing: "Pricing",
    price: "Pricing",
  };
  for (const [key, label] of Object.entries(prefixes)) {
    if (words.includes(key)) {
      const rest = words.replace(key, "").replace(/\s+/g, " ").trim();
      return rest ? `${label}: ${rest}.` : label;
    }
  }
  return `${words.charAt(0).toUpperCase()}${words.slice(1)}.`;
}

function formatInr(usd: number) {
  return `INR ${Math.round((usd || 0) * 100).toLocaleString("en-IN")}`;
}
