import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Activity, Plus, Send, Settings, Trash2 } from "lucide-react";
import { api, Run } from "../lib/api";
import { StatusBadge } from "../components/StatusBadge";

type DraftCompany = {
  name: string;
  play_link: string;
  app_store_link: string;
  website: string;
  maps_enabled: boolean;
  maps_location_hint: string;
};

const emptyDraft = (): DraftCompany => ({ name: "", play_link: "", app_store_link: "", website: "", maps_enabled: false, maps_location_hint: "India" });

export function Dashboard() {
  const [drafts, setDrafts] = useState<DraftCompany[]>([emptyDraft()]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function loadRuns() {
    const next = await api.runs();
    setRuns(next);
  }

  useEffect(() => {
    loadRuns().catch((err) => setError(err.message));
    const interval = window.setInterval(() => loadRuns().catch(() => undefined), 3000);
    return () => window.clearInterval(interval);
  }, []);

  const activeCount = useMemo(() => runs.filter((run) => ["queued", "scraping", "classifying"].includes(run.status)).length, [runs]);

  function updateDraft(index: number, patch: Partial<DraftCompany>) {
    setDrafts((items) => items.map((item, itemIndex) => (itemIndex === index ? { ...item, ...patch } : item)));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const valid = drafts.filter((draft) => draft.name.trim());
      await Promise.all(valid.map((draft) => api.submitRun(draft)));
      setDrafts([emptyDraft()]);
      await loadRuns();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not submit runs");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="page">
      <div className="topbar">
        <div>
          <p className="eyebrow">Voice of Customer</p>
          <h1>Run queue</h1>
        </div>
        <Link to="/admin" className="icon-button" title="Admin settings">
          <Settings size={18} />
        </Link>
      </div>

      <section className="panel submit-panel">
        <div className="section-heading">
          <div>
            <h2>Submit companies</h2>
            <p>{activeCount} active jobs</p>
          </div>
          <button type="button" className="secondary-button" onClick={() => setDrafts((items) => [...items, emptyDraft()])}>
            <Plus size={16} />
            Add row
          </button>
        </div>

        <form onSubmit={submit} className="batch-form">
          {drafts.map((draft, index) => (
            <div className="company-row" key={index}>
              <label>
                Company
                <input value={draft.name} onChange={(event) => updateDraft(index, { name: event.target.value })} placeholder="Razorpay" />
              </label>
              <label>
                Play Store
                <input value={draft.play_link} onChange={(event) => updateDraft(index, { play_link: event.target.value })} placeholder="https://play.google.com/store/apps/details?id=..." />
              </label>
              <label>
                App Store
                <input value={draft.app_store_link} onChange={(event) => updateDraft(index, { app_store_link: event.target.value })} placeholder="https://apps.apple.com/in/app/.../id..." />
              </label>
              <label>
                Website
                <input value={draft.website} onChange={(event) => updateDraft(index, { website: event.target.value })} placeholder="https://company.com" />
              </label>
              <label className="checkbox-label">
                <input type="checkbox" checked={draft.maps_enabled} onChange={(event) => updateDraft(index, { maps_enabled: event.target.checked })} />
                Maps
              </label>
              <label>
                Maps location
                <input value={draft.maps_location_hint} onChange={(event) => updateDraft(index, { maps_location_hint: event.target.value })} placeholder="India" />
              </label>
              <button type="button" className="icon-button row-remove" title="Remove row" onClick={() => setDrafts((items) => {
                const next = items.filter((_, itemIndex) => itemIndex !== index);
                return next.length ? next : [emptyDraft()];
              })}>
                <Trash2 size={16} />
              </button>
            </div>
          ))}
          {error ? <p className="error">{error}</p> : null}
          <button className="primary-button" disabled={busy}>
            <Send size={16} />
            Queue runs
          </button>
        </form>
      </section>

      <section className="panel">
        <div className="section-heading">
          <div>
            <h2>History</h2>
            <p>Past and active company runs</p>
          </div>
          <Activity size={18} />
        </div>
        <div className="run-list">
          {runs.map((run) => (
            <Link to={`/runs/${run.id}`} className="run-item" key={run.id}>
              <div>
                <strong>{run.company?.name || run.company_id}</strong>
                <span>{run.model_used || "model pending"}</span>
              </div>
              <StatusBadge status={run.status} />
              <span className="muted">{new Date(run.created_at).toLocaleString()}</span>
              <span className="muted">${run.cost_estimate.toFixed(3)} / ${run.budget_cap.toFixed(2)}</span>
            </Link>
          ))}
          {!runs.length ? <p className="empty">No runs yet.</p> : null}
        </div>
      </section>
    </main>
  );
}
