import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, ArrowRight, Clock3, LoaderCircle, LockKeyhole, RefreshCw, RotateCcw, Search, Trash2 } from "lucide-react";
import { api, AuthUser, getAuthUser, RunListItem, RunPage, RunStatus } from "../lib/api";
import { OnboardingFlow } from "../components/OnboardingFlow";
import { StatusBadge } from "../components/StatusBadge";

const ACTIVE = new Set(["queued", "scraping", "classifying"]);
const RUN_PAGE_SIZE = 25;
const STATUS_POLL_INTERVAL_MS = 15_000;

export function ProductWorkspace() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [runPage, setRunPage] = useState<RunPage | null>(null);
  const [email, setEmail] = useState("");
  const [query, setQuery] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [page, setPage] = useState(1);
  const [user, setUser] = useState<AuthUser | null>(() => getAuthUser());
  const [authOpen, setAuthOpen] = useState(false);
  const [setupOpen, setSetupOpen] = useState(Boolean(searchParams.get("business")));
  const [busy, setBusy] = useState(false);
  const [actionRunId, setActionRunId] = useState("");
  const [error, setError] = useState("");
  const [initialLoading, setInitialLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const runsRef = useRef<RunListItem[]>([]);
  const terminalRefreshes = useRef(new Set<string>());
  const hasLoadedRef = useRef(false);
  const lastAutomaticLoadKeyRef = useRef("");

  const loadRuns = useCallback(async (requestedPage = page, { initial = false }: { initial?: boolean } = {}) => {
    try {
      if (initial) setInitialLoading(true);
      const next = await api.runs({ page: requestedPage, page_size: RUN_PAGE_SIZE, q: appliedQuery });
      setRuns(next.items);
      setRunPage(next);
      setError("");
    } finally {
      if (initial) setInitialLoading(false);
    }
  }, [appliedQuery, page]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setPage(1);
      setAppliedQuery(query.trim());
    }, 300);
    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    const isInitialLoad = !hasLoadedRef.current;
    const loadKey = `${page}:${appliedQuery}`;
    if (lastAutomaticLoadKeyRef.current === loadKey) return;
    lastAutomaticLoadKeyRef.current = loadKey;
    loadRuns(page, { initial: isInitialLoad })
      .catch((err) => setError(err.message))
      .finally(() => {
        hasLoadedRef.current = true;
      });
  }, [loadRuns]);

  useEffect(() => {
    runsRef.current = runs;
  }, [runs]);

  const activeRunIds = useMemo(() => runs.filter((run) => ACTIVE.has(run.status)).map((run) => run.id), [runs]);
  const activeRunKey = activeRunIds.join(",");

  useEffect(() => {
    const ids = activeRunKey ? activeRunKey.split(",") : [];
    if (!ids.length) return;
    let disposed = false;

    const applyStatuses = (statuses: RunStatus[]) => {
      const byId = new Map(statuses.map((status) => [status.id, status]));
      const terminalIds = statuses
        .filter((status) => ACTIVE.has(runsRef.current.find((run) => run.id === status.id)?.status || "") && !ACTIVE.has(status.status))
        .map((status) => status.id)
        .filter((id) => !terminalRefreshes.current.has(id));

      setRuns((current) => current.map((run) => {
        const status = byId.get(run.id);
        return status ? { ...run, ...status } : run;
      }));

      if (terminalIds.length) {
        terminalIds.forEach((id) => terminalRefreshes.current.add(id));
        loadRuns().catch(() => undefined);
      }
    };

    const pollStatuses = async () => {
      if (disposed || document.visibilityState !== "visible") return;
      try {
        const response = await api.runStatuses(ids);
        if (!disposed) applyStatuses(response.items);
      } catch {
        // Preserve the existing workspace rather than replacing it with a polling error.
      }
    };

    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") pollStatuses();
    };

    document.addEventListener("visibilitychange", onVisibilityChange);
    pollStatuses();
    const interval = window.setInterval(pollStatuses, STATUS_POLL_INTERVAL_MS);
    return () => {
      disposed = true;
      document.removeEventListener("visibilitychange", onVisibilityChange);
      window.clearInterval(interval);
    };
  }, [activeRunKey, loadRuns]);

  async function refreshRuns() {
    setRefreshing(true);
    try {
      await loadRuns();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not refresh analyses.");
    } finally {
      setRefreshing(false);
    }
  }

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
      await refreshRuns();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign in");
    } finally {
      setBusy(false);
    }
  }

  async function rerun(run: RunListItem) {
    setActionRunId(run.id);
    setError("");
    try {
      const response = await api.rerun(run.id);
      await refreshRuns();
      navigate("/app/runs/" + response.run.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not queue a new run.");
    } finally {
      setActionRunId("");
    }
  }

  async function deleteRun(run: RunListItem) {
    if (ACTIVE.has(run.status)) {
      setError("Active analyses cannot be deleted.");
      return;
    }
    if (!window.confirm("Delete the analysis for " + (run.company?.name || run.company_id) + "?")) return;
    setActionRunId(run.id);
    setError("");
    try {
      await api.deleteRun(run.id);
      await refreshRuns();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete the analysis.");
    } finally {
      setActionRunId("");
    }
  }

  function logout() {
    api.logout();
    setUser(null);
    refreshRuns().catch(() => undefined);
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
        <div>
          <p className="section-marker">{setupOpen ? "New analysis" : "Workspace"}</p>
          <h1>{setupOpen ? "Tell us where to listen." : "Your customer intelligence."}</h1>
          <p>{setupOpen ? "Choose the public feedback sources before the analysis begins." : user ? "Saved runs for " + user.email + "." : "Guest runs stay in this browser until you sign in."}</p>
        </div>
        {setupOpen ? <Link className="secondary-button" to="/app"><ArrowLeft size={17} /> Back to workspace</Link> : <button className="primary-button" type="button" onClick={() => setSetupOpen(true)}>Start a new check <ArrowRight size={17} /></button>}
      </section>

      {error ? <section className="banner danger workspace-alert">{error}</section> : null}
      {setupOpen ? <section className="workspace-setup"><OnboardingFlow compact initialName={searchParams.get("business") || ""} onStarted={(runId) => navigate("/app/runs/" + runId)} /></section> : <section className="workspace-list-section">
        <div className="workspace-list-toolbar">
          <div><h2>All intelligence checks</h2><p>{initialLoading ? "Loading saved analyses…" : `${runPage?.total || 0} analyses, including live work and completed reports.`}</p></div>
          <div className="workspace-list-actions">
            <label className="search-box"><Search size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search business, stage, or status" /></label>
            <button className="icon-button" type="button" title="Refresh analyses" aria-label="Refresh analyses" disabled={refreshing} onClick={refreshRuns}><RefreshCw size={16} className={refreshing ? "spin" : ""} /></button>
          </div>
        </div>
        <div className="workspace-list">
          <div className="workspace-list-head" aria-hidden="true"><span>Business entity</span><span>Latest activity</span><span>Status</span><span>Actions</span></div>
          {initialLoading ? <div className="workspace-loading"><LoaderCircle size={20} className="spin" /><div><strong>Loading your intelligence checks</strong><span>Bringing your saved reports into the workspace.</span></div></div> : runs.map((run) => (
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
          {!initialLoading && !runs.length ? <div className="empty-slab"><Clock3 size={20} /> No intelligence checks yet.</div> : null}
        </div>
        {!initialLoading && (runPage?.pages || 1) > 1 ? <div className="pagination-row">
          <button className="secondary-button" type="button" disabled={page <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))}>Previous</button>
          <span>Page {runPage?.page || page} of {runPage?.pages || 1}</span>
          <button className="secondary-button" type="button" disabled={page >= (runPage?.pages || 1)} onClick={() => setPage((current) => Math.min(runPage?.pages || current, current + 1))}>Next</button>
        </div> : null}
      </section>}

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
