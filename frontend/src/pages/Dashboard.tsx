import { FormEvent, ReactNode, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowDownToLine, BarChart3, Check, Clock3, Database, IndianRupee, Plus, Search, Send, X } from "lucide-react";
import { api, Run } from "../lib/api";
import { StatusBadge } from "../components/StatusBadge";

type DraftCompany = {
  name: string;
  play_link: string;
  app_store_link: string;
  website: string;
  maps_enabled: boolean;
  maps_location_hint: string;
  reddit_enabled: boolean;
};

const emptyDraft = (): DraftCompany => ({
  name: "",
  play_link: "",
  app_store_link: "",
  website: "",
  maps_enabled: false,
  maps_location_hint: "India",
  reddit_enabled: false,
});

const ACTIVE = new Set(["queued", "scraping", "classifying"]);
const HISTORY_PAGE_SIZE = 25;

export function Dashboard() {
  const [draft, setDraft] = useState<DraftCompany>(emptyDraft());
  const [runs, setRuns] = useState<Run[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [historyPage, setHistoryPage] = useState(1);

  async function loadRuns() {
    const next = await api.runs();
    setRuns(next);
  }

  useEffect(() => {
    loadRuns().catch((err) => setError(err.message));
    const interval = window.setInterval(() => loadRuns().catch(() => undefined), 4000);
    return () => window.clearInterval(interval);
  }, []);

  const activeRuns = useMemo(() => runs.filter((run) => ACTIVE.has(run.status)).slice(0, 10), [runs]);
  const filteredRuns = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return runs;
    return runs.filter((run) => {
      const company = run.company?.name || run.company_id;
      return [company, run.id, run.status, run.current_stage, run.model_used || ""].some((value) => value.toLowerCase().includes(needle));
    });
  }, [runs, query]);
  const historyPages = Math.max(1, Math.ceil(filteredRuns.length / HISTORY_PAGE_SIZE));
  const pagedRuns = useMemo(() => {
    const safePage = Math.min(historyPage, historyPages);
    const start = (safePage - 1) * HISTORY_PAGE_SIZE;
    return filteredRuns.slice(start, start + HISTORY_PAGE_SIZE);
  }, [filteredRuns, historyPage, historyPages]);

  useEffect(() => {
    setHistoryPage(1);
  }, [query]);

  useEffect(() => {
    if (historyPage > historyPages) setHistoryPage(historyPages);
  }, [historyPage, historyPages]);

  const todaySpend = useMemo(() => {
    const today = new Date().toDateString();
    return runs.filter((run) => new Date(run.created_at).toDateString() === today).reduce((total, run) => total + run.cost_estimate, 0);
  }, [runs]);

  const totalBudget = useMemo(() => runs.reduce((total, run) => total + run.budget_cap, 0), [runs]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!draft.name.trim()) return;
    setBusy(true);
    setError("");
    try {
      await api.submitRun(draft);
      setDraft(emptyDraft());
      setModalOpen(false);
      await loadRuns();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not submit run");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="app-shell">
      <header className="command-header">
        <div>
          <h1>VOC Analyst</h1>
          <p>Sequential overnight queue for low-rated review intelligence.</p>
        </div>
        <div className="header-metrics">
          <HeaderMetric label="Today's spend" value={formatInr(todaySpend)} />
          <HeaderMetric label="Total budget" value={formatInr(totalBudget)} />
          <button className="primary-button square-action" onClick={() => setModalOpen(true)}>
            <Plus size={18} />
            New Analysis
          </button>
        </div>
      </header>

      <section className="queue-summary">
        <SummaryTile icon={<Clock3 size={18} />} label="Active runs" value={String(activeRuns.length)} note="Worker runs one company at a time" />
        <SummaryTile icon={<Database size={18} />} label="Queue capacity" value={`${runs.length}/250`} note="History endpoint is capped for UI speed" />
        <SummaryTile icon={<IndianRupee size={18} />} label="Avg cost/run" value={formatInr(runs.length ? runs.reduce((total, run) => total + run.cost_estimate, 0) / runs.length : 0)} note="Tracked from provider logs" />
        <SummaryTile icon={<BarChart3 size={18} />} label="Low confidence" value={String(runs.filter((run) => run.quarantine_rate > 0.2).length)} note="Quarantine rate above 20%" />
      </section>

      <section className="section-block">
        <div className="section-title-row">
          <div>
            <h2>Active Runs ({activeRuns.length})</h2>
            <p>Stage visibility is shown here and inside each company page.</p>
          </div>
        </div>
        <div className="active-grid">
          {activeRuns.map((run) => (
            <Link className="active-card" to={`/runs/${run.id}`} key={run.id}>
              <div className="card-menu">...</div>
              <h3>{run.company?.name || run.company_id}</h3>
              <p className="stage-line">{run.current_stage}</p>
              <div className="progress-track">
                <span style={{ width: `${Math.max(3, Math.round((run.progress || 0) * 100))}%` }} />
              </div>
              <div className="active-meta">
                <span><Clock3 size={15} />{durationLabel(run)}</span>
                <span>{formatInr(run.cost_estimate)}</span>
              </div>
            </Link>
          ))}
          {!activeRuns.length ? <div className="empty-slab">No active runs. Queue the next company when ready.</div> : null}
        </div>
      </section>

      <section className="history-panel">
        <div className="table-toolbar">
          <div>
            <h2>Run History</h2>
            <p>{filteredRuns.length} runs visible · page {Math.min(historyPage, historyPages)} of {historyPages}</p>
          </div>
          <label className="search-box">
            <Search size={15} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search company, run, status..." />
          </label>
          <button className="icon-button" title="Export view" type="button">
            <ArrowDownToLine size={17} />
          </button>
        </div>
        <div className="table-wrap command-table-wrap">
          <table className="command-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Project</th>
                <th>Sources</th>
                <th>Stage</th>
                <th>Status</th>
                <th>Cost</th>
                <th>Quarantine</th>
                <th>Completed</th>
              </tr>
            </thead>
            <tbody>
              {pagedRuns.map((run) => (
                <tr key={run.id} onClick={() => (window.location.href = `/runs/${run.id}`)}>
                  <td className="mono">RN-{run.id.slice(0, 5).toUpperCase()}</td>
                  <td>
                    <strong>{run.company?.name || run.company_id}</strong>
                    <span>{run.model_used || "model pending"}</span>
                  </td>
                  <td><SourcePills run={run} /></td>
                  <td>{run.current_stage}</td>
                  <td><StatusBadge status={run.status} /></td>
                  <td>{formatInr(run.cost_estimate)}</td>
                  <td>{Math.round(run.quarantine_rate * 100)}%</td>
                  <td>{run.finished_at ? new Date(run.finished_at).toLocaleString() : "In progress"}</td>
                </tr>
              ))}
              {!filteredRuns.length ? (
                <tr>
                  <td colSpan={8}>No matching runs.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
        <div className="pagination-row">
          <button className="secondary-button" disabled={historyPage <= 1} onClick={() => setHistoryPage(1)}>First</button>
          <button className="secondary-button" disabled={historyPage <= 1} onClick={() => setHistoryPage((page) => Math.max(1, page - 1))}>Previous</button>
          <span>Page {Math.min(historyPage, historyPages)} of {historyPages}</span>
          <button className="secondary-button" disabled={historyPage >= historyPages} onClick={() => setHistoryPage((page) => Math.min(historyPages, page + 1))}>Next</button>
        </div>
      </section>

      {modalOpen ? (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <form className="analysis-modal" onSubmit={submit}>
            <div className="modal-header">
              <h2>Start New Analysis</h2>
              <button type="button" className="icon-button" onClick={() => setModalOpen(false)} aria-label="Close">
                <X size={18} />
              </button>
            </div>
            <div className="modal-body">
              <label className="full-span">
                Company Name
                <input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} placeholder="e.g., FirstClub" required />
              </label>
              <label>
                Play Store URL
                <input value={draft.play_link} onChange={(event) => setDraft({ ...draft, play_link: event.target.value })} placeholder="https://play.google.com/..." />
              </label>
              <label>
                App Store URL
                <input value={draft.app_store_link} onChange={(event) => setDraft({ ...draft, app_store_link: event.target.value })} placeholder="https://apps.apple.com/..." />
              </label>
              <label className="full-span">
                Website Domain
                <input value={draft.website} onChange={(event) => setDraft({ ...draft, website: event.target.value })} placeholder="https://firstclub.site" />
              </label>

              <div className="source-toggle full-span">
                <div>
                  <strong>Google Maps Reviews</strong>
                  <span>Sorts lowest-rated first, capped at 100 India reviews.</span>
                </div>
                <Toggle checked={draft.maps_enabled} onChange={(maps_enabled) => setDraft({ ...draft, maps_enabled })} />
              </div>
              {draft.maps_enabled ? (
                <label className="full-span">
                  Maps search location
                  <input value={draft.maps_location_hint} onChange={(event) => setDraft({ ...draft, maps_location_hint: event.target.value })} placeholder="Bangalore India" />
                </label>
              ) : null}
              <div className="source-toggle full-span">
                <div>
                  <strong>Reddit Mentions</strong>
                  <span>Optional source, relevance-gated by review later.</span>
                </div>
                <Toggle checked={draft.reddit_enabled} onChange={(reddit_enabled) => setDraft({ ...draft, reddit_enabled })} />
              </div>
              <div className="analysis-rules full-span">
                <Check size={16} />
                Only 1/2/3-star rated reviews are analyzed for Play, App Store, and Maps. Reddit is included only when explicitly enabled.
              </div>
              {error ? <p className="error full-span">{error}</p> : null}
            </div>
            <div className="modal-footer">
              <button type="button" className="secondary-button" onClick={() => setModalOpen(false)}>Cancel</button>
              <button className="primary-button" disabled={busy}>
                <Send size={16} />
                Enqueue Run
              </button>
            </div>
          </form>
        </div>
      ) : null}
    </main>
  );
}

function HeaderMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="header-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function SummaryTile({ icon, label, value, note }: { icon: ReactNode; label: string; value: string; note: string }) {
  return (
    <div className="summary-tile">
      <div>{icon}</div>
      <span>{label}</span>
      <strong>{value}</strong>
      <p>{note}</p>
    </div>
  );
}

function SourcePills({ run }: { run: Run }) {
  const entries = Object.entries(run.completeness || {}).filter(([, value]) => value.status !== "disabled");
  return (
    <div className="source-pills">
      {entries.map(([source, status]) => (
        <span className={`source-pill ${status.status === "ok" ? "ok" : "warn"}`} key={source}>{source}</span>
      ))}
    </div>
  );
}

function Toggle({ checked, onChange }: { checked: boolean; onChange: (checked: boolean) => void }) {
  return (
    <button type="button" className={`toggle ${checked ? "on" : ""}`} onClick={() => onChange(!checked)} aria-pressed={checked}>
      <span />
    </button>
  );
}

function formatInr(usd: number) {
  const inr = (usd || 0) * 100;
  const options = inr > 0 && inr < 10 ? { minimumFractionDigits: 2, maximumFractionDigits: 2 } : { maximumFractionDigits: 0 };
  return `INR ${inr.toLocaleString("en-IN", options)}`;
}

function durationLabel(run: Run) {
  const start = run.started_at || run.created_at;
  const end = run.finished_at || new Date().toISOString();
  const seconds = Math.max(0, Math.floor((new Date(end).getTime() - new Date(start).getTime()) / 1000));
  const minutes = Math.floor(seconds / 60).toString().padStart(2, "0");
  const rem = (seconds % 60).toString().padStart(2, "0");
  return `${minutes}:${rem}`;
}
