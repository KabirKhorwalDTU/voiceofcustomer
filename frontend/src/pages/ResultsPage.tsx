import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Clipboard, Download, ExternalLink } from "lucide-react";
import { ResultsCharts } from "../components/Charts";
import { StatusBadge } from "../components/StatusBadge";
import { api, Results } from "../lib/api";

export function ResultsPage() {
  const { runId } = useParams();
  const [results, setResults] = useState<Results | null>(null);
  const [error, setError] = useState("");
  const [filters, setFilters] = useState({ bucket: "", theme: "", source: "", severity: "" });
  const [copied, setCopied] = useState(false);

  async function load() {
    if (!runId) return;
    const next = await api.results(runId);
    setResults(next);
  }

  useEffect(() => {
    load().catch((err) => setError(err.message));
    const interval = window.setInterval(() => {
      if (!results || ["queued", "scraping", "classifying"].includes(results.run.status)) {
        load().catch(() => undefined);
      }
    }, 3000);
    return () => window.clearInterval(interval);
  }, [runId, results?.run.status]);

  const filteredReviews = useMemo(() => {
    return (results?.reviews || []).filter((review) => {
      return (
        (!filters.bucket || review.bucket === filters.bucket) &&
        (!filters.theme || review.theme === filters.theme) &&
        (!filters.source || review.source === filters.source) &&
        (!filters.severity || String(review.severity) === filters.severity)
      );
    });
  }, [results, filters]);

  const options = useMemo(() => {
    const reviews = results?.reviews || [];
    return {
      buckets: Array.from(new Set(reviews.map((review) => review.bucket).filter(Boolean))),
      themes: Array.from(new Set(reviews.map((review) => review.theme).filter(Boolean))),
      sources: Array.from(new Set(reviews.map((review) => review.source).filter(Boolean))),
      severities: Array.from(new Set(reviews.map((review) => String(review.severity || "")).filter(Boolean))),
    };
  }, [results]);

  if (error) {
    return <main className="page"><p className="error">{error}</p></main>;
  }
  if (!results) {
    return <main className="page"><p className="empty">Loading results...</p></main>;
  }

  const completeness = Object.entries(results.run.completeness || {}) as Array<[string, { status: string }]>;
  const incomplete = completeness.filter(([, value]) => !["ok", "disabled"].includes(value.status));
  const disabled = completeness.filter(([, value]) => value.status === "disabled");
  const lowConfidence = results.run.quarantine_rate > 0.2;
  const geminiUsage = results.logs
    .filter((log) => log.provider === "gemini" && log.stage === "classification" && log.event === "stage_completed")
    .reduce(
      (totals, log) => ({
        calls: totals.calls + Number(log.details?.calls || 0),
        cost: totals.cost + log.cost_usd,
        tokens: totals.tokens + log.total_tokens,
      }),
      { calls: 0, cost: 0, tokens: 0 },
    );
  const apifyUsage = results.logs
    .filter((log) => log.provider === "apify" && log.event === "source_completed")
    .reduce((totals, log) => ({ cost: totals.cost + log.cost_usd, attempts: totals.attempts + Number(log.attempt || (log.details?.attempts as number | undefined) || 0) }), { cost: 0, attempts: 0 });
  const otherUsage = results.logs
    .filter((log) => !["gemini", "apify", ""].includes(log.provider || "") && log.cost_usd > 0)
    .reduce((total, log) => total + log.cost_usd, 0);
  const trackedCost = geminiUsage.cost + apifyUsage.cost + otherUsage;
  const storedCostDelta = Math.abs(results.run.cost_estimate - trackedCost);

  return (
    <main className="page">
      <div className="topbar">
        <div>
          <p className="eyebrow">Company results</p>
          <h1>{results.company.name}</h1>
        </div>
        <div className="top-actions">
          <StatusBadge status={results.run.status} />
          <Link to="/" className="icon-button" title="Back to dashboard">
            <ArrowLeft size={18} />
          </Link>
        </div>
      </div>

      {incomplete.length ? (
        <section className="banner warning">
          Partial data: {incomplete.map(([source, value]) => `${source} ${value.status}`).join(", ")}
        </section>
      ) : (
        <section className="banner ok">All configured sources completed.</section>
      )}
      {disabled.length ? <section className="banner muted-banner">Disabled sources: {disabled.map(([source]) => source).join(", ")}</section> : null}
      {lowConfidence ? <section className="banner danger">Low confidence: {Math.round(results.run.quarantine_rate * 100)}% of LLM batches were quarantined.</section> : null}
      {storedCostDelta > 0.005 ? (
        <section className="banner muted-banner">
          Legacy stored estimate: ${results.run.cost_estimate.toFixed(4)}. Tracked provider-log cost: ${trackedCost.toFixed(4)}.
        </section>
      ) : null}

      <section className="stats-grid">
        <Metric label="Reviews" value={String(results.summary.total_reviews || 0)} />
        <Metric label="Date range" value={`${results.summary.date_range?.start || "n/a"} to ${results.summary.date_range?.end || "n/a"}`} />
        <Metric label="Tracked cost" value={`$${trackedCost.toFixed(4)} / $${results.run.budget_cap.toFixed(2)}`} />
        <Metric label="Dedup" value={`${Math.round(results.run.dedup_ratio * 100)}%`} />
        <Metric label="Quarantine" value={`${Math.round(results.run.quarantine_rate * 100)}%`} />
      </section>

      <section className="stats-grid usage-grid">
        <Metric label="Gemini calls" value={String(geminiUsage.calls)} />
        <Metric label="Gemini tokens" value={String(geminiUsage.tokens)} />
        <Metric label="Gemini cost" value={`$${geminiUsage.cost.toFixed(4)}`} />
        <Metric label="Apify attempts" value={String(apifyUsage.attempts)} />
        <Metric label="Apify cost" value={`$${apifyUsage.cost.toFixed(4)}`} />
      </section>

      <ResultsCharts results={results} />

      <section className="panel">
        <div className="section-heading">
          <div>
            <h2>Journey logs</h2>
            <p>{results.logs.length} run events</p>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Stage</th>
                <th>Event</th>
                <th>Status</th>
                <th>Source</th>
                <th>Provider</th>
                <th>Attempt</th>
                <th>Cost</th>
                <th>Tokens</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {results.logs.map((log) => (
                <tr key={log.id}>
                  <td>{new Date(log.created_at).toLocaleTimeString()}</td>
                  <td>{log.stage}</td>
                  <td>{log.event}</td>
                  <td>{log.status}</td>
                  <td>{log.source || ""}</td>
                  <td>{log.provider || ""}</td>
                  <td>{log.attempt || ""}</td>
                  <td>${log.cost_usd.toFixed(4)}</td>
                  <td>{log.total_tokens || ""}</td>
                  <td><code>{JSON.stringify(log.details)}</code></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <div className="section-heading">
          <div>
            <h2>Tagged reviews</h2>
            <p>{filteredReviews.length} visible</p>
          </div>
          <div className="download-row">
            {(["xlsx", "csv", "json"] as const).map((fmt) => (
              <a className="secondary-button" href={api.downloadUrl(results.run.id, fmt)} key={fmt}>
                <Download size={15} />
                {fmt}
              </a>
            ))}
          </div>
        </div>
        <div className="filters">
          <Select label="Bucket" value={filters.bucket} options={options.buckets as string[]} onChange={(bucket) => setFilters({ ...filters, bucket })} />
          <Select label="Theme" value={filters.theme} options={options.themes as string[]} onChange={(theme) => setFilters({ ...filters, theme })} />
          <Select label="Source" value={filters.source} options={options.sources as string[]} onChange={(source) => setFilters({ ...filters, source })} />
          <Select label="Severity" value={filters.severity} options={options.severities as string[]} onChange={(severity) => setFilters({ ...filters, severity })} />
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Source</th>
                <th>Bucket</th>
                <th>Theme</th>
                <th>Severity</th>
                <th>Review</th>
                <th>Gloss</th>
              </tr>
            </thead>
            <tbody>
              {filteredReviews.map((review) => (
                <tr key={review.id} className={review.representative_flag ? "representative" : ""}>
                  <td>{review.source}</td>
                  <td>{review.bucket}</td>
                  <td>{review.theme?.replaceAll("_", " ")}</td>
                  <td>{review.severity}</td>
                  <td>{review.text}</td>
                  <td>{review.english_gloss}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="deck-grid">
        <div className="panel">
          <div className="section-heading">
            <div>
              <h2>Deck spec</h2>
              <p>Contract B markdown</p>
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
        <div className="panel stub-panel">
          <h2>Deck API stub</h2>
          <p>Chronicle / Gamma handoff target is reserved for post-v1.</p>
          <button className="secondary-button" disabled>
            <ExternalLink size={15} />
            Send later
          </button>
        </div>
      </section>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function Select({ label, value, options, onChange }: { label: string; value: string; options: string[]; onChange: (value: string) => void }) {
  return (
    <label>
      {label}
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">All</option>
        {options.map((option) => (
          <option value={option} key={option}>{option.replaceAll("_", " ")}</option>
        ))}
      </select>
    </label>
  );
}
