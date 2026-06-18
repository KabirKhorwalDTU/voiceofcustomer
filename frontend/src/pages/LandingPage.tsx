import { FormEvent, ReactNode, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowRight, BarChart3, CheckCircle2, LockKeyhole, MapPin, MessageSquareText, Search, Store, Users } from "lucide-react";
import { api, getAuthUser, AuthUser } from "../lib/api";

const SOURCES = ["Play Store", "App Store", "Google Maps reviews", "Reddit", "MouthShut"];

export function LandingPage() {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [website, setWebsite] = useState("");
  const [email, setEmail] = useState("");
  const [user, setUser] = useState<AuthUser | null>(() => getAuthUser());
  const [authOpen, setAuthOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function startAnalysis(event: FormEvent) {
    event.preventDefault();
    if (!name.trim() || !website.trim()) return;
    setBusy(true);
    setError("");
    try {
      const response = await api.submitPublicRun({ name, website });
      navigate(`/app/runs/${response.run.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start analysis");
    } finally {
      setBusy(false);
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
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign in");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="landing-shell">
      <nav className="landing-nav">
        <Link to="/" className="brand-lockup">
          <span>VOC</span>
          Analyst
        </Link>
        <div className="landing-nav-actions">
          <Link to="/app" className="secondary-button">Workspace</Link>
          {user ? (
            <button className="secondary-button" type="button" onClick={() => navigate("/app")}>
              <Users size={16} />
              {user.display_name || user.email}
            </button>
          ) : (
            <button className="primary-button" type="button" onClick={() => setAuthOpen(true)}>
              <LockKeyhole size={16} />
              Sign in
            </button>
          )}
        </div>
      </nav>

      <section className="hero-grid">
        <div className="hero-copy">
          <h1>Hear what customers are already saying about a consumer app.</h1>
          <p>
            Enter a company and website. VOC Analyst resolves public review surfaces, pulls low-rated feedback, and turns raw complaints into L1/L2 issue maps, quotes, and deck-ready insights.
          </p>
          <form className="public-analysis-form" onSubmit={startAnalysis}>
            <label>
              Company name
              <input value={name} onChange={(event) => setName(event.target.value)} placeholder="e.g., FirstClub" required />
            </label>
            <label>
              Company website
              <input value={website} onChange={(event) => setWebsite(event.target.value)} placeholder="https://firstclub.com" required />
            </label>
            <button className="primary-button" disabled={busy}>
              Start analysis
              <ArrowRight size={17} />
            </button>
          </form>
          {error ? <p className="error landing-error">{error}</p> : null}
          <div className="source-strip" aria-label="Supported sources">
            {SOURCES.map((source) => <span key={source}>{source}</span>)}
          </div>
        </div>

        <div className="hero-product-panel" aria-label="Product preview">
          <div className="preview-topline">
            <span>Company intelligence</span>
            <strong>Live pipeline</strong>
          </div>
          <div className="preview-search">
            <Search size={16} />
            <span>Resolving stores, maps, forums...</span>
          </div>
          <div className="preview-source-grid">
            <PreviewSource icon={<Store size={18} />} label="App stores" value="1/2/3-star reviews" />
            <PreviewSource icon={<MapPin size={18} />} label="Maps" value="India place discovery" />
            <PreviewSource icon={<MessageSquareText size={18} />} label="Social" value="Reddit + MouthShut seam" />
            <PreviewSource icon={<BarChart3 size={18} />} label="Output" value="L1/L2 themes + quotes" />
          </div>
          <div className="preview-density">
            {["Refund delays", "Poor support", "App reliability", "Service fulfilment"].map((theme, index) => (
              <div className="preview-row" key={theme}>
                <span>{theme}</span>
                <div><i style={{ width: `${86 - index * 14}%` }} /></div>
                <strong>{32 - index * 6}%</strong>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="landing-band">
        <div>
          <h2>From scattered public reviews to a founder-readable issue map.</h2>
          <p>The product keeps the heavy machinery in the background: source discovery, scraping, cleanup, L1/L2 taxonomy creation, batch classification, scoring, and export generation.</p>
        </div>
        <div className="proof-grid">
          <Proof icon={<CheckCircle2 size={18} />} title="Low-rated signal first" text="Prioritizes 1/2/3-star reviews so the output is useful for product fixes, not vanity." />
          <Proof icon={<CheckCircle2 size={18} />} title="Session-aware workspace" text="Try without login, then sign in to claim and save the run history." />
          <Proof icon={<CheckCircle2 size={18} />} title="Deck-ready output" text="Every company page includes ranked themes, L2 sub-issues, raw quotes, exports, and deck-spec copy." />
        </div>
      </section>

      {authOpen ? (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <form className="auth-modal" onSubmit={signIn}>
            <h2>Save your workspace</h2>
            <p>Use email sign-in to keep run history across devices. Any guest runs in this browser are claimed automatically.</p>
            <label>
              Email
              <input value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@company.com" type="email" required />
            </label>
            {error ? <p className="error">{error}</p> : null}
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

function PreviewSource({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="preview-source">
      <span>{icon}</span>
      <strong>{label}</strong>
      <small>{value}</small>
    </div>
  );
}

function Proof({ icon, title, text }: { icon: ReactNode; title: string; text: string }) {
  return (
    <div className="proof-card">
      <span>{icon}</span>
      <strong>{title}</strong>
      <p>{text}</p>
    </div>
  );
}
