import { FormEvent, useEffect, useMemo, useState } from "react";
import { ArrowLeft, ArrowRight, Check, MapPin, Rocket, Search, Target } from "lucide-react";
import { api, CompanyDiscovery, SubmitRunPayload } from "../lib/api";

const BUSINESS_TYPES = [
  { id: "app", label: "Digital product" },
  { id: "local_business", label: "Local business" },
  { id: "online_business", label: "Online brand" },
  { id: "creator_brand", label: "Creator brand" },
  { id: "other", label: "Other" },
];

const MISSIONS = [
  { label: "Launch prep", description: "Find friction to resolve before a release.", icon: Rocket },
  { label: "Competitive audit", description: "Surface gaps customers compare against.", icon: Target },
  { label: "Sentiment check", description: "Read the strongest praise and concern.", icon: Search },
];

const QUICK_FOCUSES = ["Delivery speed", "Product quality", "Pricing", "Customer service"];

type Props = {
  onStarted: (runId: string) => void;
  compact?: boolean;
  initialName?: string;
};

export function OnboardingFlow({ onStarted, compact = false, initialName = "" }: Props) {
  const [step, setStep] = useState<1 | 2>(1);
  const [name, setName] = useState(initialName);
  const [website, setWebsite] = useState("");
  const [businessType, setBusinessType] = useState("other");
  const [mission, setMission] = useState("Sentiment check");
  const [focus, setFocus] = useState("");
  const [discovery, setDiscovery] = useState<CompanyDiscovery | null>(null);
  const [selectedSources, setSelectedSources] = useState<string[]>([]);
  const [playLink, setPlayLink] = useState("");
  const [appStoreLink, setAppStoreLink] = useState("");
  const [mapsLocationHint, setMapsLocationHint] = useState("India");
  const [mapsUrl, setMapsUrl] = useState("");
  const [instagramUrl, setInstagramUrl] = useState("");
  const [twitterUrl, setTwitterUrl] = useState("");
  const [mouthshutUrl, setMouthshutUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (initialName) setName((current) => current || initialName);
  }, [initialName]);

  const catalog = discovery?.source_catalog || [];
  const needsPlayLink = selectedSources.includes("play") && !discovery?.play_id;
  const needsAppStoreLink = selectedSources.includes("appstore") && !discovery?.app_id;
  const selectedLabels = useMemo(
    () => catalog.filter((source) => selectedSources.includes(source.id)).map((source) => source.label),
    [catalog, selectedSources],
  );

  function resetDiscovery() {
    setDiscovery(null);
    setSelectedSources([]);
  }

  function toggleSource(id: string) {
    setSelectedSources((current) => current.includes(id) ? current.filter((source) => source !== id) : [...current, id]);
  }

  async function discoverBusiness() {
    if (!name.trim()) return;
    setBusy(true);
    setError("");
    try {
      const result = await api.discoverCompany({ name: name.trim(), website: website.trim(), business_type: businessType });
      setDiscovery(result);
      setBusinessType(result.business_type);
      setSelectedSources(result.recommended_sources);
    } catch (err) {
      setError(err instanceof Error ? err.message : "We could not find this business.");
    } finally {
      setBusy(false);
    }
  }

  async function advanceFromDetails(event: FormEvent) {
    event.preventDefault();
    if (!discovery) {
      await discoverBusiness();
      return;
    }
    if (!selectedSources.length) {
      setError("Choose at least one source to continue.");
      return;
    }
    setStep(2);
  }

  async function startAnalysis(event: FormEvent) {
    event.preventDefault();
    if (!discovery || !selectedSources.length) {
      setError("Choose at least one source to continue.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const payload: SubmitRunPayload = {
        name: name.trim(),
        website: website.trim(),
        play_link: playLink.trim(),
        app_store_link: appStoreLink.trim(),
        business_type: businessType,
        selected_sources: selectedSources,
        analysis_goals: [mission],
        analysis_focus: focus.trim(),
        maps_location_hint: mapsLocationHint.trim() || "India",
        maps_url: mapsUrl.trim(),
        instagram_url: instagramUrl.trim(),
        twitter_url: twitterUrl.trim(),
        mouthshut_url: mouthshutUrl.trim(),
      };
      const response = await api.submitRun(payload);
      onStarted(response.run.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start the analysis.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={"onboarding-flow " + (compact ? "onboarding-flow-compact" : "")} aria-label="Set up an analysis">
      <div className="setup-progress" aria-label={"Step " + step + " of 2"}>
        <span className={step === 1 ? "active" : "complete"}>01</span>
        <i />
        <span className={step === 2 ? "active" : ""}>02</span>
      </div>

      {step === 1 ? (
        <form className="setup-form" onSubmit={advanceFromDetails}>
          <div className="setup-copy">
            <p className="section-marker">Step 1 of 2</p>
            <h2>Tell us about the business.</h2>
            <p>Start with the public footprint, then choose the places worth listening to.</p>
          </div>

          <div className="business-details">
            <label className="field-label field-label-wide">
              Business name
              <span className="input-with-icon">
                <Search size={18} />
                <input value={name} onChange={(event) => { setName(event.target.value); resetDiscovery(); }} placeholder="Enter a business name, address, or domain" autoComplete="organization" required />
              </span>
            </label>
            <label className="field-label">
              Website <small>Optional</small>
              <input value={website} onChange={(event) => { setWebsite(event.target.value); resetDiscovery(); }} placeholder="yourbusiness.com" inputMode="url" />
            </label>
            <label className="field-label">
              Business type
              <select value={businessType} onChange={(event) => { setBusinessType(event.target.value); resetDiscovery(); }}>
                {BUSINESS_TYPES.map((type) => <option value={type.id} key={type.id}>{type.label}</option>)}
              </select>
            </label>
          </div>

          {discovery ? (
            <div className="source-setup">
              <div className="entity-match">
                <span className="company-monogram">{discovery.icon_text}</span>
                <div><strong>{discovery.name}</strong><small>{discovery.domain || "Public business match"}</small></div>
                <span className="verified-label">Verified entity</span>
              </div>
              <div className="source-setup-heading">
                <div><p className="section-marker">Source selection</p><h3>Choose where to listen.</h3><p>All available public sources are listed below. We preselect the sensible starting set for this business.</p></div>
                <span>{selectedSources.length} of {catalog.length} selected</span>
              </div>
              <div className="source-choice-grid">
                {catalog.map((source) => {
                  const selected = selectedSources.includes(source.id);
                  const recommended = discovery.recommended_sources.includes(source.id);
                  return (
                    <button className={"source-choice " + (selected ? "selected" : "")} type="button" onClick={() => toggleSource(source.id)} key={source.id} aria-pressed={selected}>
                      <span className="source-choice-marker">{selected ? <Check size={14} /> : null}</span>
                      <span><strong>{source.label}</strong><small>{source.short_description} · up to {source.cap.toLocaleString("en-IN")} items</small></span>
                      {recommended ? <em>Recommended</em> : null}
                    </button>
                  );
                })}
              </div>

              <div className="source-followups">
                <div className="followup-heading"><MapPin size={17} /><strong>Matching details</strong></div>
                {needsPlayLink ? <label className="field-label">Google Play link <input value={playLink} onChange={(event) => setPlayLink(event.target.value)} placeholder="play.google.com/store/apps/..." /></label> : null}
                {needsAppStoreLink ? <label className="field-label">App Store link <input value={appStoreLink} onChange={(event) => setAppStoreLink(event.target.value)} placeholder="apps.apple.com/..." /></label> : null}
                {selectedSources.includes("maps") ? <div className="two-field-row"><label className="field-label">Google Maps link <input value={mapsUrl} onChange={(event) => setMapsUrl(event.target.value)} placeholder="Google Maps business link" /></label><label className="field-label">City or area <input value={mapsLocationHint} onChange={(event) => setMapsLocationHint(event.target.value)} placeholder="e.g. Indiranagar, Bengaluru" /></label></div> : null}
                {selectedSources.includes("instagram") ? <label className="field-label">Instagram profile or post <input value={instagramUrl} onChange={(event) => setInstagramUrl(event.target.value)} placeholder="instagram.com/yourbusiness" /></label> : null}
                {selectedSources.includes("twitter") ? <label className="field-label">X profile <input value={twitterUrl} onChange={(event) => setTwitterUrl(event.target.value)} placeholder="x.com/yourbusiness" /></label> : null}
                {selectedSources.includes("mouthshut") ? <label className="field-label">MouthShut review page <input value={mouthshutUrl} onChange={(event) => setMouthshutUrl(event.target.value)} placeholder="mouthshut.com/product-reviews/..." /></label> : null}
              </div>
            </div>
          ) : (
            <div className="discovery-note"><span>01</span><p>We will match the business and recommend its likely review, map, app, and conversation sources.</p></div>
          )}

          <div className="setup-actions">
            <span>{discovery ? "Usually a few minutes, depending on selected sources." : "Business match only. No scan yet."}</span>
            <button className="primary-button" disabled={busy}>{busy ? "Finding sources..." : discovery ? "Next: choose the mission" : "Find customer sources"}<ArrowRight size={17} /></button>
          </div>
        </form>
      ) : (
        <form className="setup-form mission-form" onSubmit={startAnalysis}>
          <div className="setup-copy">
            <p className="section-marker">Step 2 of 2</p>
            <h2>What should it listen for?</h2>
            <p>Choose the lens for this run, then add a specific concern or opportunity.</p>
          </div>
          <div className="mission-layout">
            <div>
              <fieldset className="mission-fieldset">
                <legend>Mission focus</legend>
                <div className="mission-grid">
                  {MISSIONS.map(({ label, description, icon: Icon }) => (
                    <button className={"mission-option " + (mission === label ? "selected" : "")} type="button" onClick={() => setMission(label)} aria-pressed={mission === label} key={label}>
                      <Icon size={20} /><span><strong>{label}</strong><small>{description}</small></span>
                    </button>
                  ))}
                </div>
              </fieldset>
              <label className="field-label focus-field">What else should we focus on?<textarea value={focus} onChange={(event) => setFocus(event.target.value)} placeholder="e.g. recent delivery delays, staff behavior, or pricing changes" rows={5} /></label>
              <div className="quick-focuses">{QUICK_FOCUSES.map((item) => <button type="button" className="quick-focus" onClick={() => setFocus((current) => current ? current + "; " + item : item)} key={item}>{item}</button>)}</div>
            </div>
            <aside className="mission-context">
              <p className="section-marker">Target acquired</p>
              <div className="entity-match"><span className="company-monogram">{discovery?.icon_text}</span><div><strong>{discovery?.name}</strong><small>{discovery?.domain || "Public business match"}</small></div></div>
              <dl><div><dt>Sources</dt><dd>{selectedLabels.join(", ") || "Selected sources"}</dd></div><div><dt>Mission</dt><dd>{mission}</dd></div><div><dt>Region</dt><dd>{mapsLocationHint || "India"}</dd></div></dl>
            </aside>
          </div>
          <div className="setup-actions split-actions"><button type="button" className="secondary-button" onClick={() => setStep(1)}><ArrowLeft size={17} /> Back</button><button className="primary-button" disabled={busy}>{busy ? "Starting analysis..." : "Generate insights"}<ArrowRight size={17} /></button></div>
        </form>
      )}
      {error ? <p className="error onboarding-error">{error}</p> : null}
    </section>
  );
}
