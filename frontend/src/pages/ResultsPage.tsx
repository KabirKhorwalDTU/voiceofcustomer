import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { Activity, ArrowLeft, CheckCircle2, ChevronDown, ChevronRight, Clock3, Download, ListChecks, Printer, Radar, RotateCcw } from "lucide-react";
import { ResultsCharts } from "../components/Charts";
import { StatusBadge } from "../components/StatusBadge";
import { api, Results, ReviewPage, RunLog } from "../lib/api";

const ACTIVE = new Set(["queued", "scraping", "classifying"]);
const ANALYST_STEPS = [
  { stage: "scraping", label: "Collect public feedback" },
  { stage: "cleaning", label: "Clean and select relevant feedback" },
  { stage: "theme_discovery", label: "Find recurring themes" },
  { stage: "classification", label: "Classify themes and sub-issues" },
  { stage: "synthesis", label: "Write your executive readout" },
];

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
  const location = useLocation();
  const inProductWorkspace = location.pathname.startsWith("/app");
  const basePath = location.pathname.startsWith("/kabir") || location.pathname.startsWith("/runs/") ? "/kabir" : "/app";
  const [results, setResults] = useState<Results | null>(null);
  const [reviewPage, setReviewPage] = useState<ReviewPage | null>(null);
  const [filters, setFilters] = useState<ReviewFilters>(emptyFilters);
  const [expandedThemes, setExpandedThemes] = useState<Set<string>>(new Set());
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [rerunning, setRerunning] = useState(false);
  const [error, setError] = useState("");
  const [initialLoading, setInitialLoading] = useState(true);

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
    setResults(null);
    setReviewPage(null);
    setError("");
    setInitialLoading(true);
    loadResults()
      .catch((err) => setError(err.message))
      .finally(() => setInitialLoading(false));
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

  const geminiUsage = useMemo(() => rollupProvider(results, "gemini"), [results]);
  const apifyUsage = useMemo(() => rollupProvider(results, "apify"), [results]);
  const trackedCost = Math.max(results?.run.cost_estimate || 0, geminiUsage.cost + apifyUsage.cost);
  const topTheme = results?.themes?.[0];
  const insightSummary = toSummaryRecord(results?.summary?.insight_summary);
  const feedbackRisk = toSummaryRecord(results?.summary?.feedback_risk);
  const feedbackRiskScore = Number(feedbackRisk.score || 0);
  const recommendedActions = Array.isArray(insightSummary.recommended_actions) ? insightSummary.recommended_actions as Array<Record<string, unknown>> : [];
  const firstAction = recommendedActions[0] || {};
  const selectedSources = (results?.company.selected_sources || []).map(formatSource);
  const usedSources = Object.entries(results?.summary.source_mix || {})
    .filter(([, count]) => Number(count) > 0)
    .map(([source]) => formatSource(source));
  const reportSources = usedSources.length ? usedSources : selectedSources;
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
      navigate(`${basePath}/runs/${response.run.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start rerun");
    } finally {
      setRerunning(false);
    }
  }

  if (error && !results) {
    return <main className="app-shell run-state-shell"><section className="run-state-card"><p className="section-marker">Analysis unavailable</p><h1>We could not load this report.</h1><p>{error}</p><button className="primary-button" type="button" onClick={() => { setError(""); setInitialLoading(true); loadResults().catch((err) => setError(err.message)).finally(() => setInitialLoading(false)); }}>Try again</button></section></main>;
  }

  if (!results) {
    return <RunLoadingState loading={initialLoading} />;
  }

  if (ACTIVE.has(results.run.status)) {
    const currentIndex = analystStepIndex(results.run.current_stage, results.run.stage_detail, results.run.progress);
    const nextStep = ANALYST_STEPS[Math.min(ANALYST_STEPS.length - 1, currentIndex + 1)];
    const liveSources = reportSources.length ? reportSources : ["the selected public feedback sources"];
    return (
      <main className="app-shell analyst-page">
        <header className="editorial-app-header report-header">
          <Link to="/" className="brand-lockup"><span>VOC</span>Voice of Customer</Link>
          <div className="report-header-meta">
            <StatusBadge status={results.run.status} />
            <Link to={inProductWorkspace ? "/app" : "/kabir"} className="icon-button" title="Back to workspace" aria-label="Back to workspace"><ArrowLeft size={18} /></Link>
          </div>
        </header>
        <section className="analyst-work-panel">
          <div className="analyst-main">
            <p className="section-marker">Live analysis</p>
            <h1>The analyst is at work.</h1>
            <p>We are turning {liveSources.join(", ")} into a usable customer feedback report for {results.company.name}. You can leave this page safely; it updates from the live worker state.</p>
            <div className="live-progress">
              <div><span>Analyzing feedback data</span><strong>{Math.round((results.run.progress || 0) * 100)}%</strong></div>
              <i><b style={{ width: Math.max(3, Math.round((results.run.progress || 0) * 100)) + "%" }} /></i>
              <small>{results.run.current_stage}{results.run.stage_detail ? " · " + results.run.stage_detail : ""}</small>
            </div>
            <div className="analyst-step-list" aria-label="Analysis steps">
              {ANALYST_STEPS.map((step, index) => (
                <div className={index < currentIndex ? "complete" : index === currentIndex ? "active" : "pending"} key={step.stage}>
                  <span>{index < currentIndex ? "Done" : index === currentIndex ? "Now" : "Next"}</span>
                  <strong>{step.label}</strong>
                </div>
              ))}
            </div>
            <div className="analyst-next-step"><Clock3 size={18} /><div><span>Coming next</span><strong>{nextStep.label}</strong><p>Batch classification can take a little longer after source collection. The report appears automatically when this pass is complete.</p></div></div>
          </div>
          <aside className="preliminary-signals">
            <div className="signal-heading"><Radar size={20} /><h2>What your report will include</h2></div>
            {results.themes.slice(0, 2).map((theme, index) => (
              <article className="signal-card" key={theme.id}>
                <span className={index === 0 ? "tag tag-good" : "tag tag-purple"}>{index === 0 ? "Emerging" : "Notable"}</span>
                <h3>{theme.count} mentions of {humanizeTheme(theme.theme)}</h3>
                <p>Detected in the feedback processed so far.</p>
              </article>
            ))}
            {!results.themes.length ? <div className="analyst-deliverables"><div><ListChecks size={17} /><span><strong>Issue map</strong><small>Clear L1 themes and L2 sub-issues.</small></span></div><div><Activity size={17} /><span><strong>Evidence</strong><small>Representative customer voices behind each signal.</small></span></div><div><CheckCircle2 size={17} /><span><strong>Next actions</strong><small>Mission-aware actions grounded in the feedback.</small></span></div></div> : null}
            <p>Early indicators appear only once there is real classified feedback. Until then, we show the work in progress, not invented insights.</p>
          </aside>
        </section>
      </main>
    );
  }

  return (
    <main className="app-shell detail-shell">
      <header className="editorial-app-header report-header">
        <div>
          <Link to="/" className="brand-lockup"><span>VOC</span>Voice of Customer</Link>
        </div>
        <div className="report-header-meta">
          <StatusBadge status={results.run.status} />
          <button className="secondary-button" onClick={rerunCurrent} disabled={rerunning} title="Queue a fresh run for this company">
            <RotateCcw size={16} />
            Run again
          </button>
          <button className="secondary-button" onClick={() => window.print()} title="Print this customer intelligence report">
            <Printer size={16} />
            Print
          </button>
          <Link to={inProductWorkspace ? "/app" : "/kabir"} className="icon-button" title="Back to dashboard">
            <ArrowLeft size={18} />
          </Link>
        </div>
      </header>

      <section className="report-masthead">
        <div>
          <p className="section-marker">Customer intelligence report</p>
          <h1>{results.company.name}: customer feedback report.</h1>
          <p>Evidence from {reportSources.join(", ") || "the selected public feedback sources"}, organized into the decisions that deserve attention now.</p>
        </div>
        <div className="report-masthead-status"><strong>{results.run.status === "partial" ? "Partial report" : "Report ready"}</strong><span>{reportSources.length || 0} source{reportSources.length === 1 ? "" : "s"} used · {results.summary.total_reviews || 0} reviews</span></div>
      </section>

      {incomplete.length ? (
        <section className="banner warning report-notice">
          Partial data: {incomplete.map(([source, value]) => `${source} ${value.status}`).join(", ")}
        </section>
      ) : null}
      {lowConfidence ? (
        <section className="banner danger report-notice">
          Low confidence: quarantine {Math.round(results.run.quarantine_rate * 100)}%, L1 other {Math.round(otherShare * 100)}%.
        </section>
      ) : null}
      {error ? <section className="banner danger report-notice">{error}</section> : null}

      <section className="executive-summary">
        <div className="health-score">
          <p className="section-marker">Customer feedback risk</p>
          <strong>{feedbackRiskScore}</strong>
          <small>/ 100</small>
          <span>{String(feedbackRisk.evidence_grade || "early")} evidence · selected feedback</span>
        </div>
        <div className="executive-pulse">
          <div><p className="section-marker">Executive pulse</p><span className="tag tag-good">Evidence-led</span></div>
          <h2>{String(insightSummary.headline || (topTheme ? humanizeTheme(topTheme.theme) : "Customer signal summary"))}</h2>
          <p>{String(insightSummary.executive_pulse || (topTheme ? humanizeTheme(topTheme.theme) + " is the clearest current signal, appearing in " + topTheme.count + " selected feedback items." : "The strongest customer themes will appear as classification completes."))}</p>
        </div>
        <div className="feedback-risk">
          <p className="section-marker">Mission action</p>
          <h2>{String(firstAction.title || "What to do next")}</h2>
          <p>{String(firstAction.rationale || feedbackRisk.scope || (topTheme ? "Review the underlying evidence for " + humanizeTheme(topTheme.theme) + " before assigning an owner or response." : "No concentrated risk has been identified yet."))}</p>
        </div>
      </section>

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
      </section>

      <section className="stats-grid results-stats">
        <Metric label="Selected feedback" value={String(results.summary.total_reviews || 0)} note="1-3 star reviews and enabled public sources" />
        <Metric label="Listening posts" value={reportSources.join(" · ") || "Selected sources"} note={`${reportSources.length || 0} source${reportSources.length === 1 ? "" : "s"} contributed usable feedback`} />
        <Metric label="Feedback period" value={formatDateRange(results.summary.date_range)} note="Most recent selected public feedback" />
        <Metric label="Tracked cost" value={`${formatInr(trackedCost)} of ${formatInr(results.run.budget_cap)}`} note={`Gemini ${formatInr(geminiUsage.cost)} · Apify ${formatInr(apifyUsage.cost)}`} />
        <Metric label="Quality check" value={`${Math.round((1 - otherShare) * 100)}% mapped`} note={`${Math.round(otherShare * 100)}% other · ${Math.round(results.run.quarantine_rate * 100)}% quarantined`} />
      </section>

      <ThemeDensityPanel results={results} expandedThemes={expandedThemes} onToggle={toggleTheme} />

      <ResultsCharts results={results} />

      <section className="section-block source-quality-section">
        <div className="section-title-row">
          <div>
            <h2>Source quality</h2>
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
                  <td>{formatSource(row.source)}</td>
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

      <section className="history-panel review-history" data-print="exclude">
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
              <button className="secondary-button" type="button" onClick={() => api.downloadRun(results.run.id, fmt).catch((err) => setError(err.message))} key={fmt}>
                <Download size={15} />
                {fmt}
              </button>
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

function RunLoadingState({ loading }: { loading: boolean }) {
  return (
    <main className="app-shell analyst-page run-state-shell">
      <header className="editorial-app-header report-header"><Link to="/" className="brand-lockup"><span>VOC</span>Voice of Customer</Link></header>
      <section className="run-state-card launch-state-card">
        <p className="section-marker">Preparing analysis</p>
        <h1>{loading ? "Setting up your analyst." : "Your analysis is starting."}</h1>
        <p>We are connecting the selected sources and reserving the worker. This page will switch to the live analysis view as soon as the run record is ready.</p>
        <div className="launch-steps"><span className="active">01 Create analysis</span><span>02 Collect feedback</span><span>03 Build your report</span></div>
      </section>
    </main>
  );
}

function analystStepIndex(currentStage: string, stageDetail: string, progress: number) {
  const text = `${currentStage} ${stageDetail}`.toLowerCase();
  if (/scrap|collect|source/.test(text)) return 0;
  if (/clean|dedup|select/.test(text)) return 1;
  if (/discover|taxonomy|theme/.test(text) && !/classif/.test(text)) return 2;
  if (/classif|assign|batch/.test(text)) return 3;
  if (/synth|export|report|deck/.test(text)) return 4;
  return Math.min(ANALYST_STEPS.length - 1, Math.floor(Math.max(0, progress || 0) * ANALYST_STEPS.length));
}

function formatSource(source: string) {
  const labels: Record<string, string> = {
    play: "Google Play",
    appstore: "App Store",
    maps: "Google Maps",
    instagram: "Instagram",
    twitter: "X / Twitter",
    reddit: "Reddit",
    mouthshut: "MouthShut",
  };
  return labels[source] || source;
}

function formatDateRange(value?: { start?: string; end?: string }) {
  if (!value?.start || !value?.end) return "Date range unavailable";
  const start = new Date(value.start);
  const end = new Date(value.end);
  if (Number.isNaN(start.valueOf()) || Number.isNaN(end.valueOf())) return `${value.start} to ${value.end}`;
  const options: Intl.DateTimeFormatOptions = { month: "short", year: "numeric" };
  return `${start.toLocaleDateString("en-IN", options)} — ${end.toLocaleDateString("en-IN", options)}`;
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

function rollupProvider(results: Results | null, provider: "gemini" | "apify") {
  const fromLogs = rollupLogs(results?.logs || [], provider);
  if (fromLogs.cost || fromLogs.tokens || fromLogs.calls || results?.logs?.length) {
    return fromLogs;
  }
  const rollup = results?.summary?.cost_rollup?.[provider] || {};
  return {
    calls: Number(rollup.calls || rollup.events || 0),
    cost: Number(rollup.cost || 0),
    tokens: Number(rollup.tokens || rollup.total_tokens || 0),
  };
}

function toSummaryRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
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
