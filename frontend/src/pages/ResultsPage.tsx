import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, ChevronDown, ChevronRight, Clipboard, Download, ExternalLink, RotateCcw } from "lucide-react";
import { ResultsCharts } from "../components/Charts";
import { StatusBadge } from "../components/StatusBadge";
import { api, Results, ReviewPage, RunLog } from "../lib/api";

const ACTIVE = new Set(["queued", "scraping", "classifying"]);

type ReviewFilters = {
  review_hash: string;
  source: string;
  theme: string;
  l2_theme: string;
  rating: string;
  date_query: string;
  text_query: string;
};

const emptyFilters: ReviewFilters = {
  review_hash: "",
  source: "",
  theme: "",
  l2_theme: "",
  rating: "",
  date_query: "",
  text_query: "",
};

export function ResultsPage() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const [results, setResults] = useState<Results | null>(null);
  const [reviewPage, setReviewPage] = useState<ReviewPage | null>(null);
  const [filters, setFilters] = useState<ReviewFilters>(emptyFilters);
  const [expandedThemes, setExpandedThemes] = useState<Set<string>>(new Set());
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [copied, setCopied] = useState(false);
  const [rerunning, setRerunning] = useState(false);
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
  }, [
    runId,
    page,
    pageSize,
    filters.review_hash,
    filters.source,
    filters.theme,
    filters.l2_theme,
    filters.rating,
    filters.date_query,
    filters.text_query,
  ]);

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
  const otherShare = Number(results?.summary.other_share || 0);
  const lowConfidence = Boolean(results && (results.run.quarantine_rate > 0.2 || results.summary.low_confidence));

  const sourceOptions = useMemo(() => Object.keys(results?.summary.source_mix || {}).sort(), [results]);
  const themeOptions = useMemo(() => Array.from(new Set((results?.themes || []).map((theme) => theme.theme))).sort(), [results]);
  const l2Options = useMemo(() => {
    const values = new Set<string>();
    (results?.themes || []).forEach((theme) => {
      (theme.l2_subthemes || []).forEach((row) => values.add(row.label));
    });
    return Array.from(values).sort();
  }, [results]);
  const ratingOptions = useMemo(() => Object.keys(results?.summary.rating_distribution || {}).sort(), [results]);

  const geminiUsage = useMemo(() => rollupLogs(results?.logs || [], "gemini"), [results]);
  const apifyUsage = useMemo(() => rollupLogs(results?.logs || [], "apify"), [results]);
  const trackedCost = Math.max(results?.run.cost_estimate || 0, geminiUsage.cost + apifyUsage.cost);
  const topTheme = results?.themes?.[0];
  const deckPreview = useMemo(() => {
    const lines = (results?.deck_spec || "").split("\n").filter((line) => line.trim() && !line.startsWith("#"));
    return lines.slice(0, 4).join(" ");
  }, [results?.deck_spec]);

  function updateFilter(key: keyof ReviewFilters, value: string) {
    setPage(1);
    setFilters((current) => ({ ...current, [key]: value }));
  }

  useEffect(() => {
    if (!results) return;
    const defaults = results.themes
      .filter((theme) => theme.l2_subthemes?.length)
      .slice(0, 2)
      .map((theme) => theme.id);
    setExpandedThemes(new Set(defaults));
  }, [results?.run.id]);

  function toggleTheme(themeId: string) {
    setExpandedThemes((current) => {
      const next = new Set(current);
      if (next.has(themeId)) {
        next.delete(themeId);
      } else {
        next.add(themeId);
      }
      return next;
    });
  }

  async function rerunCurrent() {
    if (!results) return;
    setRerunning(true);
    setError("");
    try {
      const response = await api.rerun(results.run.id);
      navigate(`/runs/${response.run.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start rerun");
    } finally {
      setRerunning(false);
    }
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
          <button className="secondary-button" onClick={rerunCurrent} disabled={rerunning} title="Queue a fresh run for this company">
            <RotateCcw size={16} />
            Rerun
          </button>
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
      {lowConfidence ? (
        <section className="banner danger">
          Low confidence: quarantine {Math.round(results.run.quarantine_rate * 100)}%, L1 other {Math.round(otherShare * 100)}%.
        </section>
      ) : null}

      <section className="insight-grid">
        <div className="insight-card">
          <p className="eyebrow">Insight Synthesis</p>
          <h2>{topTheme ? `Top signal: ${humanizeTheme(topTheme.theme)}` : "Waiting for classified themes"}</h2>
          <p>
            {topTheme
              ? `${topTheme.count} selected reviews · ${Math.round(Number(topTheme.share ?? topTheme.normalized_frequency ?? 0) * 100)}% of classified feedback · score ${Number(topTheme.theme_score || 0).toFixed(3)}.`
              : "The run will summarize the strongest signal once classification completes."}
          </p>
          {topTheme?.l2_subthemes?.length ? (
            <div className="insight-l2-line">
              {topTheme.l2_subthemes.slice(0, 3).map((row) => (
                <span key={row.label}>{humanizeTheme(row.label)} {Math.round(Number(row.score || 0) * 100)}%</span>
              ))}
            </div>
          ) : null}
        </div>
        <div className="deck-mini">
          <div className="section-title-row">
            <h2>Deck Spec</h2>
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
          <p>{deckPreview || "Deck-spec will appear after synthesis."}</p>
        </div>
      </section>

      <section className="stats-grid results-stats">
        <Metric label="Selected reviews" value={String(results.summary.total_reviews || 0)} note="1/2/3-star rated sources, plus Reddit only if enabled" />
        <Metric label="Date range" value={`${results.summary.date_range?.start || "n/a"} to ${results.summary.date_range?.end || "n/a"}`} />
        <Metric label="Tracked cost" value={`${formatInr(trackedCost)} / ${formatInr(results.run.budget_cap)}`} note={`Gemini ${formatInr(geminiUsage.cost)} · Apify ${formatInr(apifyUsage.cost)}`} />
        <Metric label="Gemini tokens" value={geminiUsage.tokens.toLocaleString("en-IN")} note={`${geminiUsage.calls} logged calls`} />
        <Metric label="Other / quarantine" value={`${Math.round(otherShare * 100)}% / ${Math.round(results.run.quarantine_rate * 100)}%`} note="Target L1 other below 15%" />
      </section>

      <ThemeDensityPanel results={results} expandedThemes={expandedThemes} onToggle={toggleTheme} />

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
          <div className="download-row">
            <button className="secondary-button" type="button" onClick={() => { setFilters(emptyFilters); setPage(1); }}>
              Clear filters
            </button>
            {(["xlsx", "csv", "json"] as const).map((fmt) => (
              <a className="secondary-button" href={api.downloadUrl(results.run.id, fmt)} key={fmt}>
                <Download size={15} />
                {fmt}
              </a>
            ))}
          </div>
        </div>

        <div className="column-filter-row rows-only-filter">
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
                <th>L1 Theme</th>
                <th>L2 Sub-issue</th>
                <th>Review</th>
              </tr>
              <tr className="column-search-row">
                <th><ColumnInput value={filters.review_hash} placeholder="Hash" onChange={(value) => updateFilter("review_hash", value)} /></th>
                <th><InlineSelect value={filters.source} options={sourceOptions} onChange={(value) => updateFilter("source", value)} /></th>
                <th><InlineSelect value={filters.rating} options={ratingOptions} onChange={(value) => updateFilter("rating", value)} /></th>
                <th><ColumnInput value={filters.date_query} placeholder="YYYY-MM" onChange={(value) => updateFilter("date_query", value)} /></th>
                <th><InlineSelect value={filters.theme} options={themeOptions} display={humanizeTheme} onChange={(value) => updateFilter("theme", value)} /></th>
                <th><InlineSelect value={filters.l2_theme} options={l2Options} display={humanizeTheme} onChange={(value) => updateFilter("l2_theme", value)} /></th>
                <th><ColumnInput value={filters.text_query} placeholder="Search review text" onChange={(value) => updateFilter("text_query", value)} /></th>
              </tr>
            </thead>
            <tbody>
              {(reviewPage?.items || []).map((review) => (
                <tr key={review.id} className={review.representative_flag ? "representative" : ""}>
                  <td className="mono">{review.review_hash.slice(0, 8)}</td>
                  <td>{review.source}</td>
                  <td>{review.rating ?? "n/a"}</td>
                  <td>{review.date || "n/a"}</td>
                  <td>{humanizeTheme(review.theme)}</td>
                  <td>{humanizeTheme(review.l2_theme)}</td>
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

function ThemeDensityPanel({
  results,
  expandedThemes,
  onToggle,
}: {
  results: Results;
  expandedThemes: Set<string>;
  onToggle: (themeId: string) => void;
}) {
  const themes = results.themes.slice(0, 8);
  const maxScore = Math.max(...themes.map((theme) => Number(theme.theme_score || 0)), 0.001);
  const l2Count = themes.reduce((total, theme) => total + (theme.l2_subthemes?.length || 0), 0);
  const otherShare = Number(results.summary.other_share || 0);

  return (
    <section className="section-block density-panel">
      <div className="section-title-row">
        <div>
          <h2>Thematic Density</h2>
          <p>L1 themes by share and score, with L2 sub-issues expanded for parents with at least 5 rows.</p>
        </div>
        <div className={`density-badge ${otherShare > 0.15 ? "warn" : ""}`}>
          Other {Math.round(otherShare * 100)}% · {l2Count} L2
        </div>
      </div>
      <div className="density-list">
        {themes.map((theme) => {
          const expanded = expandedThemes.has(theme.id);
          const hasL2 = Boolean(theme.l2_subthemes?.length);
          const scorePct = Math.max(2, Math.round((Number(theme.theme_score || 0) / maxScore) * 100));
          const sharePct = Math.round(Number(theme.share ?? theme.normalized_frequency ?? 0) * 100);
          return (
            <div className="density-row" key={theme.id}>
              <button className="density-main" type="button" onClick={() => hasL2 && onToggle(theme.id)} disabled={!hasL2}>
                <span className="density-label">{humanizeTheme(theme.theme)}</span>
                <span className="density-bar" aria-hidden="true">
                  <span style={{ width: `${scorePct}%` }} />
                </span>
                <span className="density-impact">{theme.count} rows · {sharePct}% · score {Number(theme.theme_score || 0).toFixed(3)}</span>
                {hasL2 ? (expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />) : <span className="density-empty">No L2</span>}
              </button>
              {expanded && hasL2 ? (
                <div className="l2-stack">
                  {theme.l2_subthemes.slice(0, 10).map((row) => {
                    const quote = row.top_quotes?.[0]?.text;
                    return (
                      <div className="l2-row" key={row.label}>
                        <div className="l2-row-top">
                          <span>{humanizeTheme(row.label)}</span>
                          <strong>{Math.round(Number(row.score || 0) * 100)}%</strong>
                        </div>
                        <div className="l2-track">
                          <span style={{ width: `${Math.max(3, Math.round(Number(row.score || 0) * 100))}%` }} />
                        </div>
                        {quote ? <p>"{String(quote).slice(0, 150)}"</p> : null}
                      </div>
                    );
                  })}
                </div>
              ) : null}
            </div>
          );
        })}
        {!themes.length ? <div className="empty-slab">No themes yet.</div> : null}
      </div>
    </section>
  );
}

function ColumnInput({ value, placeholder, onChange }: { value: string; placeholder: string; onChange: (value: string) => void }) {
  return <input className="column-search-input" value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} />;
}

function InlineSelect({ value, options, display, onChange }: { value: string; options: string[]; display?: (value: string) => string; onChange: (value: string) => void }) {
  return (
    <select className="column-search-input" value={value} onChange={(event) => onChange(event.target.value)}>
      <option value="">All</option>
      {options.map((option) => (
        <option value={option} key={option}>{display ? display(option) : option}</option>
      ))}
    </select>
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
  if (theme === "login_or_kyc") return "Login & KYC.";
  if (theme === "support_quality") return "Support quality.";
  if (theme === "app_reliability") return "App reliability.";
  if (theme === "delivery_or_service_fulfillment") return "Delivery & service fulfillment.";
  if (theme === "quality_or_professionalism") return "Quality & professionalism.";
  if (theme === "pricing_or_fees") return "Pricing & fees.";
  if (theme === "pricing_and_promotions") return "Pricing & promotions.";
  if (theme === "pricing_and_value") return "Pricing & value.";
  if (theme === "unfair_refund_policies_and_failure_to_process_refunds") {
    return "Refunds: unfair policies & failures to process.";
  }
  const words = cleanThemeWords(theme.replaceAll("_", " ").trim());
  const lowerWords = words.toLowerCase();
  if (lowerWords.includes("overpriced") && !lowerWords.startsWith("pricing")) {
    return `Pricing: ${words}.`;
  }
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
    if (words === key) return label;
    if (words.startsWith(`${key} `)) {
      const rest = words.slice(key.length).replace(/\s+/g, " ").trim();
      if (rest.startsWith("and ")) return `${label} & ${rest.slice(4)}.`;
      return rest ? `${label}: ${rest}.` : label;
    }
  }
  return `${words.charAt(0).toUpperCase()}${words.slice(1)}.`;
}

function cleanThemeWords(words: string) {
  const replacements: Record<string, string> = {
    "overd products": "overpriced products",
    "poor ,": "poor,",
    "in- feedback": "in-app feedback",
    "behind /registration": "behind login/registration",
    "without mandatory.": "without mandatory registration.",
    "without mandatory ": "without mandatory registration ",
  };
  return Object.entries(replacements)
    .reduce((text, [oldText, newText]) => text.replaceAll(oldText, newText), words)
    .replace(/\s+/g, " ")
    .trim();
}

function formatInr(usd: number) {
  const inr = (usd || 0) * 100;
  const options = inr > 0 && inr < 10 ? { minimumFractionDigits: 2, maximumFractionDigits: 2 } : { maximumFractionDigits: 0 };
  return `INR ${inr.toLocaleString("en-IN", options)}`;
}
