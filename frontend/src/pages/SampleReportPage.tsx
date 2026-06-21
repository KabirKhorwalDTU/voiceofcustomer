import { ArrowLeft, CheckCircle2, Printer } from "lucide-react";
import { Link } from "react-router-dom";

const themes = [
  { label: "Service availability", share: 20, detail: "Items unavailable at checkout", quote: "Most of the products I need are unavailable when I open the app." },
  { label: "Delivery & fulfilment", share: 17, detail: "Late delivery and cancellation", quote: "The order arrived late and the essential items were cancelled without a useful update." },
  { label: "Product quality", share: 14, detail: "Damaged or expired items", quote: "The fruit quality was not what the listing promised." },
  { label: "App reliability", share: 14, detail: "Login and checkout failure", quote: "The app froze when I tried to complete payment." },
];

export function SampleReportPage() {
  return (
    <main className="app-shell detail-shell sample-detail-shell">
      <header className="editorial-app-header report-header">
        <Link to="/" className="brand-lockup"><span>VOC</span>Voice of Customer</Link>
        <div className="report-header-meta">
          <span className="sample-status"><CheckCircle2 size={15} /> Illustrative sample</span>
          <button className="secondary-button" type="button" onClick={() => window.print()}><Printer size={16} /> Print sample</button>
          <Link to="/" className="icon-button" aria-label="Back to home" title="Back to home"><ArrowLeft size={18} /></Link>
        </div>
      </header>

      <section className="report-masthead sample-masthead">
        <div>
          <p className="section-marker">Sample customer intelligence report</p>
          <h1>First Club: where grocery trust is breaking.</h1>
          <p>An illustrative India-focused report built from the kind of 1-3 star Google Play and App Store feedback a grocery business would receive.</p>
        </div>
        <div className="report-masthead-status"><strong>Sample report</strong><span>1,098 selected reviews</span></div>
      </section>

      <section className="executive-summary">
        <div className="health-score">
          <p className="section-marker">Customer feedback risk</p>
          <strong>74</strong>
          <small>/ 100</small>
          <span>illustrative · selected feedback</span>
        </div>
        <div className="executive-pulse">
          <div><p className="section-marker">Executive pulse</p><span className="tag tag-risk">Priority signal</span></div>
          <h2>Availability and fulfilment failures are compounding.</h2>
          <p>Customers are not describing one isolated problem. Low stock, cancellations, delayed delivery, and quality misses are converging into a reliability story.</p>
        </div>
        <div className="feedback-risk">
          <p className="section-marker">Suggested first move</p>
          <h2>Make stock and delivery expectations honest.</h2>
          <p>Surface local availability before checkout, explain substitutions clearly, and create a visible recovery path for late or incomplete orders.</p>
        </div>
      </section>

      <section className="stats-grid results-stats">
        <SampleMetric label="Selected feedback" value="1,098" note="1-3 star app-store reviews" />
        <SampleMetric label="Listening posts" value="2" note="Google Play and App Store" />
        <SampleMetric label="Market context" value="India" note="grocery and quick-commerce" />
        <SampleMetric label="Quality signal" value="86% mapped" note="14% held as other" />
        <SampleMetric label="Report focus" value="Reliability" note="availability, delivery, quality" />
      </section>

      <section className="section-block density-panel">
        <div className="section-title-row">
          <div><h2>What customers are repeating</h2><p>The highest-volume themes, with the specific experiences behind them.</p></div>
          <span className="density-badge">4 priority themes</span>
        </div>
        <div className="density-list">
          {themes.map((theme) => (
            <article className="sample-density-row" key={theme.label}>
              <div><strong>{theme.label}</strong><span>{theme.detail}</span></div>
              <div className="density-bar"><span style={{ width: `${theme.share * 4}%` }} /></div>
              <b>{theme.share}%</b>
              <p>“{theme.quote}”</p>
            </article>
          ))}
        </div>
      </section>

      <section className="sample-evidence-grid">
        <article><p className="eyebrow">Feedback pattern</p><h2>1-star reviews dominate the selected feedback.</h2><div className="sample-chart-bars"><span style={{ height: "100%" }}><i>1★</i></span><span style={{ height: "34%" }}><i>2★</i></span><span style={{ height: "42%" }}><i>3★</i></span></div></article>
        <article><p className="eyebrow">Source coverage</p><h2>Google Play carries the volume; App Store adds a second customer lens.</h2><div className="source-coverage"><span><b>1,006</b> Google Play</span><span><b>92</b> App Store</span></div></article>
      </section>

      <section className="sample-voices">
        <div className="section-title-row"><div><h2>Representative customer voices</h2><p>Examples of the evidence an owner can open before taking action.</p></div></div>
        <div className="sample-voice-grid">
          <blockquote>“Items keep showing as available, then disappear after I pay.”<span>Service availability</span></blockquote>
          <blockquote>“Delivery was late, the essentials were missing, and no one helped.”<span>Delivery &amp; fulfilment</span></blockquote>
          <blockquote>“The produce quality is inconsistent. It does not feel worth the price.”<span>Product quality</span></blockquote>
        </div>
      </section>
    </main>
  );
}

function SampleMetric({ label, value, note }: { label: string; value: string; note: string }) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong><small>{note}</small></div>;
}
