import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Save } from "lucide-react";
import { api, Settings as SettingsType } from "../lib/api";

export function Admin() {
  const [settings, setSettings] = useState<SettingsType | null>(null);
  const [sourceWeights, setSourceWeights] = useState("");
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.settings()
      .then((value) => {
        setSettings(value);
        setSourceWeights(JSON.stringify(value.source_weights, null, 2));
      })
      .catch((err) => setError(err.message));
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!settings) return;
    setSaved(false);
    setError("");
    try {
      const updated = await api.updateSettings({ ...settings, source_weights: JSON.parse(sourceWeights) });
      setSettings(updated);
      setSourceWeights(JSON.stringify(updated.source_weights, null, 2));
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save settings");
    }
  }

  return (
    <main className="page narrow">
      <div className="topbar">
        <div>
          <p className="eyebrow">Admin</p>
          <h1>Runtime settings</h1>
        </div>
        <Link to="/" className="icon-button" title="Back to dashboard">
          <ArrowLeft size={18} />
        </Link>
      </div>

      <section className="panel">
        {!settings ? <p className="empty">Loading settings...</p> : (
          <form className="settings-form" onSubmit={submit}>
            <label>
              Provider
              <select value={settings.provider} onChange={(event) => setSettings({ ...settings, provider: event.target.value })}>
                <option value="gemini">Gemini</option>
                <option value="deepseek">DeepSeek</option>
              </select>
            </label>
            <label>
              Model
              <input value={settings.model} onChange={(event) => setSettings({ ...settings, model: event.target.value })} />
            </label>
            <label>
              Max reviews
              <input type="number" value={settings.max_reviews} onChange={(event) => setSettings({ ...settings, max_reviews: Number(event.target.value) })} />
            </label>
            <label>
              Batch size
              <input type="number" value={settings.batch_size} onChange={(event) => setSettings({ ...settings, batch_size: Number(event.target.value) })} />
            </label>
            <label>
              Recency window days
              <input type="number" value={settings.recency_window_days} onChange={(event) => setSettings({ ...settings, recency_window_days: Number(event.target.value) })} />
            </label>
            <label>
              Dedup threshold
              <input type="number" step="0.01" value={settings.dedup_threshold} onChange={(event) => setSettings({ ...settings, dedup_threshold: Number(event.target.value) })} />
            </label>
            <label>
              Per-run budget USD
              <input type="number" step="0.01" value={settings.per_run_budget_usd} onChange={(event) => setSettings({ ...settings, per_run_budget_usd: Number(event.target.value) })} />
            </label>
            <label className="full-span">
              Source weights
              <textarea value={sourceWeights} onChange={(event) => setSourceWeights(event.target.value)} rows={7} />
            </label>
            {error ? <p className="error">{error}</p> : null}
            {saved ? <p className="success">Saved.</p> : null}
            <button className="primary-button">
              <Save size={16} />
              Save settings
            </button>
          </form>
        )}
      </section>
    </main>
  );
}

