import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ArrowRight, Clock3, LockKeyhole, RotateCcw, Search, Trash2 } from "lucide-react";
import { api, AuthUser, getAuthUser, Run } from "../lib/api";
import { OnboardingFlow } from "../components/OnboardingFlow";
import { StatusBadge } from "../components/StatusBadge";

const ACTIVE = new Set(["queued", "scraping", "classifying"]);

export function ProductWorkspace() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [runs, setRuns] = useState<Run[]>([]);
  const [email, setEmail] = useState("");
  const [query, setQuery] = useState("");
  const [user, setUser] = useState<AuthUser | null>(() => getAuthUser());
  const [authOpen, setAuthOpen] = useState(false);
  const [setupOpen, setSetupOpen] = useState(Boolean(searchParams.get("business")));
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
      navigate("/app/runs/" + response.run.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not queue a new run.");
    } finally {
      setActionRunId("");
    }
  }

  async function deleteRun(run: Run) {
    if (ACTIVE.has(run.status)) {
      setError("Active analyses cannot be deleted.");
      return;
    }
    if (!window.confirm("Delete the analysis for " + (run.company?.name || run.company_id) + "?")) return;
    setActionRunId(run.id);
    setError("");
    try {
      await api.deleteRun(run.id);
      await loadRuns();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete the analysis.");
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
    <main className="app-shell workspace-shell">
      <header className="editorial-app-header">
        <Link to="/" className="brand-lockup"><span>VOC</span>Voice of Customer</Link>
        <div className="editorial-app-actions">
          {user ? <button className="secondary-button" type="button" onClick={logout}>Log out</button> : <button className="secondary-button" type="button" onClick={() => setAuthOpen(true)}><LockKeyhole size={16} /> Sign in</button>}
        </div>
      </header>

      <section className="workspace-title">
        <div><p className="section-marker">Workspace</p><h1>Your customer intelligence.</h1><p>{user ? "Saved runs for " + user.email + "." : "Guest runs stay in this browser until you sign in."}</p></div>
        <button className="primary-button" type="button" onClick={() => setSetupOpen((current) => !current)}>{setupOpen ? "Close setup" : "Start a new check"} <ArrowRight size={17} /></button>
      </section>

      {error ? <section className="banner danger workspace-alert">{error}</section> : null}
      {setupOpen ? <section className="workspace-setup"><OnboardingFlow compact initialName={searchParams.get("business") || ""} onStarted={async (runId) => { await loadRuns(); navigate("/app/runs/" + runId); }} /></section> : null}

      <section className="workspace-list-section">
        <div className="workspace-list-toolbar">
          <div><h2>All intelligence checks</h2><p>{filteredRuns.length} analyses, including live work and completed reports.</p></div>
          <label className="search-box"><Search size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search business, stage, or status" /></label>
        </div>
        <div className="workspace-list">
          <div className="workspace-list-head" aria-hidden="true"><span>Business entity</span><span>Latest activity</span><span>Status</span><span>Actions</span></div>
          {filteredRuns.map((run) => (
            <article className={"workspace-run " + (ACTIVE.has(run.status) ? "is-active" : "")} key={run.id}>
              <button className="workspace-run-main" type="button" onClick={() => navigate("/app/runs/" + run.id)}>
                <span className="workspace-company"><i>{(run.company?.name || run.company_id).slice(0, 1).toUpperCase()}</i><span><strong>{run.company?.name || run.company_id}</strong><small>{run.company?.domain || run.model_used || "Customer feedback analysis"}</small></span></span>
                <span className="workspace-stage">{ACTIVE.has(run.status) ? <><em>Analyst at work</em><strong>{run.current_stage}</strong><span className="mini-progress"><i style={{ width: Math.max(3, Math.round((run.progress || 0) * 100)) + "%" }} /></span></> : <><strong>{run.finished_at ? new Date(run.finished_at).toLocaleString() : run.current_stage}</strong><small>{run.stage_detail || "Report available"}</small></>}</span>
                <StatusBadge status={run.status} />
              </button>
              <div className="workspace-row-actions">
                <button className="icon-button" type="button" title="Run again" aria-label="Run again" disabled={actionRunId === run.id} onClick={() => rerun(run)}><RotateCcw size={16} /></button>
                <button className="icon-button danger-action" type="button" title="Delete analysis" aria-label="Delete analysis" disabled={ACTIVE.has(run.status) || actionRunId === run.id} onClick={() => deleteRun(run)}><Trash2 size={16} /></button>
              </div>
            </article>
          ))}
          {!filteredRuns.length ? <div className="empty-slab"><Clock3 size={20} /> No intelligence checks yet.</div> : null}
        </div>
      </section>

      {authOpen ? (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="workspace-sign-in-title">
          <form className="auth-modal" onSubmit={signIn}>
            <h2 id="workspace-sign-in-title">Save your workspace</h2>
            <p>Claim guest analyses and keep this workspace across devices.</p>
            <label className="field-label">Email<input value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@company.com" type="email" required /></label>
            <div className="modal-footer compact-footer"><button type="button" className="secondary-button" onClick={() => setAuthOpen(false)}>Cancel</button><button className="primary-button" disabled={busy}>Continue</button></div>
          </form>
        </div>
      ) : null}
    </main>
  );
}
