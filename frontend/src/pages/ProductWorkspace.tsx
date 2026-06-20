import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Clock3, LockKeyhole, RotateCcw, Search, Trash2 } from "lucide-react";
import { api, AuthUser, getAuthUser, Run } from "../lib/api";
import { StatusBadge } from "../components/StatusBadge";
import { OnboardingFlow } from "../components/OnboardingFlow";

const ACTIVE = new Set(["queued", "scraping", "classifying"]);

export function ProductWorkspace() {
  const navigate = useNavigate();
  const [runs, setRuns] = useState<Run[]>([]);
  const [email, setEmail] = useState("");
  const [query, setQuery] = useState("");
  const [user, setUser] = useState<AuthUser | null>(() => getAuthUser());
  const [authOpen, setAuthOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actionRunId, setActionRunId] = useState("");
  const [error, setError] = useState("");

  async function loadRuns() {
    const next = await api.runs();
    setRuns(next);
  }

  useEffect(() => {
    loadRuns().catch((err) => setError(err.message));
    const interval = window.setInterval(() => loadRuns().catch(() => undefined), 5000);
    return () => window.clearInterval(interval);
  }, []);

  const activeRuns = useMemo(() => runs.filter((run) => ACTIVE.has(run.status)), [runs]);
  const filteredRuns = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return runs;
    return runs.filter((run) => [run.company?.name || "", run.current_stage, run.status, run.id].some((value) => value.toLowerCase().includes(needle)));
  }, [runs, query]);

  async function signIn(event: FormEvent) {
    event.preventDefault();
    if (!email.trim()) return;
    setBusy(true);
    setError("");
    try {
      const response = await api.login(email);
      setUser(response.user);
      setAuthOpen(false);
      setEmail("");
      await loadRuns();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign in");
    } finally {
      setBusy(false);
    }
  }

  async function rerun(run: Run) {
    setActionRunId(run.id);
    setError("");
    try {
      const response = await api.rerun(run.id);
      await loadRuns();
      navigate(`/app/runs/${response.run.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not queue rerun");
    } finally {
      setActionRunId("");
    }
  }

  async function deleteRun(run: Run) {
    if (ACTIVE.has(run.status)) {
      setError("Active runs cannot be deleted.");
      return;
    }
    if (!window.confirm(`Delete run for ${run.company?.name || run.company_id}?`)) return;
    setActionRunId(run.id);
    setError("");
    try {
      await api.deleteRun(run.id);
      await loadRuns();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete run");
    } finally {
      setActionRunId("");
    }
  }

  function logout() {
    api.logout();
    setUser(null);
    loadRuns().catch(() => undefined);
  }

  return (
    <main className="app-shell product-shell">
      <header className="command-header">
        <div>
          <Link to="/" className="brand-lockup compact-brand"><span>VOC</span> Analyst</Link>
          <h1>Workspace</h1>
          <p>{user ? `Saved runs for ${user.email}` : "Guest runs are saved in this browser. Sign in to keep them across devices."}</p>
        </div>
        <div className="header-metrics">
          <button className="secondary-button" type="button" onClick={() => setAuthOpen(true)}>
            <LockKeyhole size={16} />
            {user ? "Switch account" : "Sign in to save"}
          </button>
          {user ? <button className="secondary-button" type="button" onClick={logout}>Log out</button> : null}
        </div>
      </header>

      {error ? <section className="banner danger">{error}</section> : null}

      <section className="workspace-grid">
        <section className="section-block product-submit-panel">
          <div className="section-title-row">
            <div>
              <h2>New analysis</h2>
              <p>Start with a business name. We recommend sources, then ask only for the details that improve matching.</p>
            </div>
          </div>
          <OnboardingFlow compact onStarted={async (runId) => { await loadRuns(); navigate(`/app/runs/${runId}`); }} />
        </section>

        <section className="section-block workspace-status-panel">
          <div className="section-title-row">
            <div>
              <h2>Active work</h2>
              <p>{activeRuns.length} runs currently queued, scraping, or classifying.</p>
            </div>
          </div>
          <div className="workspace-active-list">
            {activeRuns.slice(0, 5).map((run) => (
              <Link to={`/app/runs/${run.id}`} className="workspace-active-row" key={run.id}>
                <strong>{run.company?.name || run.company_id}</strong>
                <span>{run.current_stage}</span>
                <div className="progress-track">
                  <i style={{ width: `${Math.max(3, Math.round((run.progress || 0) * 100))}%` }} />
                </div>
              </Link>
            ))}
            {!activeRuns.length ? <div className="empty-slab">No active runs right now.</div> : null}
          </div>
        </section>
      </section>

      <section className="history-panel">
        <div className="table-toolbar">
          <div>
            <h2>Run history</h2>
            <p>{filteredRuns.length} visible runs</p>
          </div>
          <label className="search-box">
            <Search size={15} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search runs..." />
          </label>
        </div>
        <div className="table-wrap command-table-wrap">
          <table className="command-table">
            <thead>
              <tr>
                <th>Company</th>
                <th>Stage</th>
                <th>Status</th>
                <th>Cost</th>
                <th>Quarantine</th>
                <th>Updated</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredRuns.map((run) => (
                <tr key={run.id} onClick={() => navigate(`/app/runs/${run.id}`)}>
                  <td>
                    <strong>{run.company?.name || run.company_id}</strong>
                    <span>{run.company?.domain || run.model_used || "source discovery pending"}</span>
                  </td>
                  <td>{run.current_stage}</td>
                  <td><StatusBadge status={run.status} /></td>
                  <td>{formatInr(run.cost_estimate)}</td>
                  <td>{Math.round(run.quarantine_rate * 100)}%</td>
                  <td>{run.finished_at ? new Date(run.finished_at).toLocaleString() : <span><Clock3 size={13} /> In progress</span>}</td>
                  <td>
                    <div className="row-actions" onClick={(event) => event.stopPropagation()}>
                      <button className="icon-button tiny-action" type="button" title="Rerun" disabled={actionRunId === run.id} onClick={() => rerun(run)}>
                        <RotateCcw size={15} />
                      </button>
                      <button className="icon-button tiny-action danger-action" type="button" title="Delete" disabled={ACTIVE.has(run.status) || actionRunId === run.id} onClick={() => deleteRun(run)}>
                        <Trash2 size={15} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {!filteredRuns.length ? <tr><td colSpan={7}>No runs yet. Start an analysis above.</td></tr> : null}
            </tbody>
          </table>
        </div>
      </section>

      {authOpen ? (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <form className="auth-modal" onSubmit={signIn}>
            <h2>Sign in</h2>
            <p>Save your run history and claim any guest analyses from this browser.</p>
            <label>
              Email
              <input value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@company.com" type="email" required />
            </label>
            <div className="modal-footer compact-footer">
              <button type="button" className="secondary-button" onClick={() => setAuthOpen(false)}>Cancel</button>
              <button className="primary-button" disabled={busy}>Continue</button>
            </div>
          </form>
        </div>
      ) : null}
    </main>
  );
}

function formatInr(usd: number) {
  const inr = (usd || 0) * 100;
  const options = inr > 0 && inr < 10 ? { minimumFractionDigits: 2, maximumFractionDigits: 2 } : { maximumFractionDigits: 0 };
  return `INR ${inr.toLocaleString("en-IN", options)}`;
}
