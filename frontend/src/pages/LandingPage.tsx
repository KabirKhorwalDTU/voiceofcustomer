import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowRight, BarChart3, LockKeyhole, MapPin, MessageSquareText, Search, Smartphone } from "lucide-react";
import { api, AuthUser, getAuthUser } from "../lib/api";

const SOURCES = [
  { label: "Google Play", note: "Recent 1-3 star Android reviews", icon: Smartphone },
  { label: "App Store", note: "Recent 1-3 star iPhone reviews", icon: Smartphone },
  { label: "Google Maps", note: "Low-rated reviews from India places", icon: MapPin },
  { label: "Instagram", note: "Brand comments and public mentions", icon: MessageSquareText },
  { label: "X / Twitter", note: "Public posts, replies, and mentions", icon: MessageSquareText },
  { label: "Reddit", note: "Public customer discussions", icon: MessageSquareText },
  { label: "MouthShut", note: "India consumer reviews", icon: BarChart3 },
];

export function LandingPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [user, setUser] = useState<AuthUser | null>(() => getAuthUser());
  const [authOpen, setAuthOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

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
    <main className="landing-shell editorial-home">
      <nav className="editorial-nav">
        <Link to="/" className="brand-lockup"><span>VOC</span>Voice of Customer</Link>
        <div className="editorial-nav-actions">
          <Link to="/app" className="secondary-button">Workspace</Link>
          {user ? <button className="secondary-button" type="button" onClick={() => navigate("/app")}>{user.display_name || user.email}</button> : <button className="primary-button" type="button" onClick={() => setAuthOpen(true)}><LockKeyhole size={16} /> Sign in</button>}
        </div>
      </nav>

      <section className="home-grid">
        <div className="home-main">
          <p className="section-marker marker-green">Customer intelligence</p>
          <h1>Understand what your customers really want.</h1>
          <p className="home-intro">Follow public feedback from the places customers already use, then turn it into a clear issue map with the evidence behind every signal.</p>
          <QuickStart onStart={(businessName) => navigate("/app?business=" + encodeURIComponent(businessName))} />
          {error ? <p className="error landing-error">{error}</p> : null}

          <section className="latest-checks" aria-label="Example intelligence checks">
            <div className="section-heading-inline">
              <div><h2>Latest intelligence checks</h2><p>Illustrative outcomes from the workspace.</p></div>
              <span className="live-label">Live</span>
            </div>
            <div className="check-list">
              <article className="check-row"><div><strong>First Club</strong><p>Availability and delivery reliability are the most repeated grocery-app concerns.</p></div><span className="tag tag-risk">Fulfilment risk</span></article>
              <article className="check-row"><div><strong>Swiggy</strong><p>Peak-hour delivery experience is driving the sharpest customer feedback.</p></div><span className="tag tag-good">Service signal</span></article>
            </div>
          </section>
        </div>

        <aside className="home-rail">
          <section>
            <h2>Monitored sources</h2>
            <div className="source-rail">
              {SOURCES.map(({ label, note, icon: Icon }) => <div className="source-rail-item" key={label}><Icon size={21} /><span><strong>{label}</strong><small>{note}</small></span></div>)}
            </div>
          </section>
          <section className="sample-cta">
            <h2>Explore a full report</h2>
            <p>See how First Club's public grocery-app feedback becomes themes, evidence, and next actions.</p>
            <button className="sample-report-button" type="button" onClick={() => navigate("/sample/first-club")}>Open First Club sample <ArrowRight size={18} /></button>
          </section>
          <blockquote className="field-note">“The work begins with what people are already saying, not a blank survey.”</blockquote>
        </aside>
      </section>

      <section className="sample-report" id="sample-report">
        <div className="sample-report-intro"><p className="section-marker">Complete sample report</p><h2>First Club: grocery feedback, made actionable.</h2><p>An India-focused illustrative report. It uses no customer data and never calls the analysis API.</p><button className="secondary-button" type="button" onClick={() => navigate("/sample/first-club")}>View the full report <ArrowRight size={16} /></button></div>
        <div className="sample-report-grid">
          <section className="sample-score"><span>Customer feedback risk</span><strong>74</strong><small>/ 100</small><div className="score-bars"><i style={{ width: "74%" }} /><i style={{ width: "61%" }} /><i style={{ width: "48%" }} /></div></section>
          <section className="sample-pulse"><span className="tag tag-risk">Priority signal</span><h3>Availability and delivery reliability need attention.</h3><p>First Club customers are clear on the pattern: unavailable items, late delivery, and product-quality misses compound into a trust problem.</p><div><span>1,098 selected reviews</span><span>Google Play + App Store</span><span>Bengaluru grocery context</span></div></section>
        </div>
        <div className="sample-themes">
          {[["Delivery & fulfilment", "192 mentions", "72%", "risk"], ["Service availability", "219 mentions", "82%", "good"], ["Product quality", "150 mentions", "56%", "purple"]].map(([label, amount, width, kind]) => <div className="sample-theme" key={label}><span>{label}</span><div><i className={kind} style={{ width }} /></div><small>{amount}</small></div>)}
        </div>
      </section>

      {authOpen ? (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="sign-in-title">
          <form className="auth-modal" onSubmit={signIn}>
            <h2 id="sign-in-title">Save your workspace</h2>
            <p>Sign in to keep run history across devices. Any guest runs in this browser will be claimed.</p>
            <label className="field-label">Email<input value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@company.com" type="email" required /></label>
            {error ? <p className="error">{error}</p> : null}
            <div className="modal-footer compact-footer"><button type="button" className="secondary-button" onClick={() => setAuthOpen(false)}>Cancel</button><button className="primary-button" disabled={busy}>Continue</button></div>
          </form>
        </div>
      ) : null}
    </main>
  );
}

function QuickStart({ onStart }: { onStart: (businessName: string) => void }) {
  const [businessName, setBusinessName] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    const next = businessName.trim();
    if (next) onStart(next);
  }

  return (
    <form className="quick-start-form" onSubmit={submit}>
      <label className="sr-only" htmlFor="business-name">Business name or website</label>
      <Search size={20} aria-hidden="true" />
      <input id="business-name" value={businessName} onChange={(event) => setBusinessName(event.target.value)} placeholder="Enter your business name or URL" autoComplete="organization" required />
      <button className="primary-button" type="submit">Start a free check <ArrowRight size={17} /></button>
      <small>Business match only. You choose sources before any analysis starts.</small>
    </form>
  );
}
