import { FormEvent, useMemo, useState } from "react";
import { ArrowLeft, ArrowRight, Check, MapPin, Search, Sparkles } from "lucide-react";
import { api, CompanyDiscovery, SubmitRunPayload } from "../lib/api";

const BUSINESS_TYPES = [
  { id: "app", label: "App or digital service" },
  { id: "local_business", label: "Local shop or service" },
  { id: "creator_brand", label: "Creator or personal brand" },
  { id: "online_business", label: "Online business or brand" },
  { id: "other", label: "Something else" },
];

const GOALS = [
  "Find recurring customer problems",
  "Understand what people love",
  "Spot product or service requests",
  "Track brand conversations",
];

type Props = {
  onStarted: (runId: string) => void;
  compact?: boolean;
};

export function OnboardingFlow({ onStarted, compact = false }: Props) {
  const [step, setStep] = useState<1 | 2>(1);
  const [name, setName] = useState("");
  const [website, setWebsite] = useState("");
  const [businessType, setBusinessType] = useState("other");
  const [goals, setGoals] = useState<string[]>([GOALS[0]]);
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

  const catalog = discovery?.source_catalog || [];
  const needsPlayLink = selectedSources.includes("play") && !discovery?.play_id;
  const needsAppStoreLink = selectedSources.includes("appstore") && !discovery?.app_id;

  const selectedLabels = useMemo(
    () => catalog.filter((source) => selectedSources.includes(source.id)).map((source) => source.label),
    [catalog, selectedSources],
  );

  function toggle(items: string[], value: string, setter: (next: string[]) => void) {
    setter(items.includes(value) ? items.filter((item) => item !== value) : [...items, value]);
  }

  async function continueToSources(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError("");
    try {
      const result = await api.discoverCompany({ name: name.trim(), website: website.trim(), business_type: businessType });
      setDiscovery(result);
      setBusinessType(result.business_type);
      setSelectedSources(result.recommended_sources);
      setStep(2);
    } catch (err) {
      setError(err instanceof Error ? err.message : "We could not look up this business.");
    } finally {
      setBusy(false);
    }
  }

  async function startAnalysis(event: FormEvent) {
    event.preventDefault();
    if (!discovery || !selectedSources.length) {
      setError("Pick at least one place to listen for customers.");
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
        analysis_goals: goals,
        maps_location_hint: mapsLocationHint.trim() || "India",
        maps_url: mapsUrl.trim(),
        instagram_url: instagramUrl.trim(),
        twitter_url: twitterUrl.trim(),
        mouthshut_url: mouthshutUrl.trim(),
      };
      const response = await api.submitRun(payload);
      onStarted(response.run.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start analysis.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={`guided-onboarding ${compact ? "guided-onboarding-compact" : ""}`} aria-label="Start an analysis">
      <div className="onboarding-progress" aria-label={`Step ${step} of 2`}>
        <span className={step === 1 ? "active" : "done"}>1</span>
        <i />
        <span className={step === 2 ? "active" : ""}>2</span>
      </div>

      {step === 1 ? (
        <form className="onboarding-form" onSubmit={continueToSources}>
          <div className="onboarding-heading">
            <span className="eyebrow"><Sparkles size={14} /> Start with the basics</span>
            <h2>Tell us about the business.</h2>
            <p>We will find the public places customers are already talking. A website helps, but is not required.</p>
          </div>
          <div className="onboarding-fields two-up">
            <label>
              Business name
              <input value={name} onChange={(event) => setName(event.target.value)} placeholder="e.g., Riya's Bakery" autoComplete="organization" required />
            </label>
            <label>
              Website <small>Optional</small>
              <input value={website} onChange={(event) => setWebsite(event.target.value)} placeholder="riyasbakery.in" inputMode="url" />
            </label>
          </div>
          <fieldset className="choice-fieldset">
            <legend>What kind of business is this?</legend>
            <div className="choice-grid business-choice-grid">
              {BUSINESS_TYPES.map((type) => (
                <button className={businessType === type.id ? "choice-chip selected" : "choice-chip"} type="button" onClick={() => setBusinessType(type.id)} key={type.id}>
                  {type.label}
                </button>
              ))}
            </div>
          </fieldset>
          <fieldset className="choice-fieldset">
            <legend>What would be most useful?</legend>
            <div className="choice-grid goal-choice-grid">
              {GOALS.map((goal) => (
                <button className={goals.includes(goal) ? "choice-chip selected" : "choice-chip"} type="button" onClick={() => toggle(goals, goal, setGoals)} key={goal}>
                  {goals.includes(goal) ? <Check size={14} /> : null}
                  {goal}
                </button>
              ))}
            </div>
          </fieldset>
          <div className="onboarding-actions">
            <button className="primary-button" disabled={busy}>
              {busy ? "Looking it up..." : "Find customer sources"}
              <ArrowRight size={17} />
            </button>
          </div>
        </form>
      ) : (
        <form className="onboarding-form" onSubmit={startAnalysis}>
          <div className="business-match-row">
            <span className="company-monogram">{discovery?.icon_text}</span>
            <div>
              <strong>{discovery?.name}</strong>
              <small>{discovery?.domain || "We will use the business name to search"}</small>
            </div>
            <button className="text-button" type="button" onClick={() => setStep(1)}>Edit</button>
          </div>
          <div className="onboarding-heading compact-heading">
            <span className="eyebrow"><Search size={14} /> Recommended listening posts</span>
            <h2>We picked a sensible starting set.</h2>
            <p>Tap anything to include or remove it. We only run the sources you leave selected.</p>
          </div>
          <div className="source-choice-grid">
            {catalog.map((source) => {
              const selected = selectedSources.includes(source.id);
              const recommended = discovery?.recommended_sources.includes(source.id);
              return (
                <button className={selected ? "source-choice selected" : "source-choice"} type="button" onClick={() => toggle(selectedSources, source.id, setSelectedSources)} key={source.id}>
                  <span className="source-choice-marker">{selected ? <Check size={15} /> : null}</span>
                  <span>
                    <strong>{source.label}</strong>
                    <small>{source.short_description}</small>
                  </span>
                  <em>{recommended ? "Recommended" : `Up to ${source.cap.toLocaleString()} items`}</em>
                </button>
              );
            })}
          </div>

          <div className="identity-followups">
            <div className="followup-heading">
              <MapPin size={17} />
              <div><strong>Help us match the right pages</strong><small>Only complete the fields for sources you selected. Everything here is optional, but improves accuracy.</small></div>
            </div>
            {needsPlayLink ? <label>Google Play link <input value={playLink} onChange={(event) => setPlayLink(event.target.value)} placeholder="play.google.com/store/apps/details?id=..." /></label> : null}
            {needsAppStoreLink ? <label>App Store link <input value={appStoreLink} onChange={(event) => setAppStoreLink(event.target.value)} placeholder="apps.apple.com/..." /></label> : null}
            {selectedSources.includes("maps") ? <div className="onboarding-fields two-up"><label>Google Maps link <small>Optional</small><input value={mapsUrl} onChange={(event) => setMapsUrl(event.target.value)} placeholder="Google Maps business link" /></label><label>City or area <small>Optional</small><input value={mapsLocationHint} onChange={(event) => setMapsLocationHint(event.target.value)} placeholder="e.g., Indiranagar, Bengaluru" /></label></div> : null}
            {selectedSources.includes("instagram") ? <label>Instagram profile or recent post/reel link <small>Optional - a post/reel link lets us include its comments</small><input value={instagramUrl} onChange={(event) => setInstagramUrl(event.target.value)} placeholder="instagram.com/yourbusiness or instagram.com/p/..." /></label> : null}
            {selectedSources.includes("twitter") ? <label>X / Twitter profile link <small>Optional - helps us collect replies to your account</small><input value={twitterUrl} onChange={(event) => setTwitterUrl(event.target.value)} placeholder="x.com/yourbusiness" /></label> : null}
            {selectedSources.includes("mouthshut") ? <label>MouthShut review-page link <small>Required for this source</small><input value={mouthshutUrl} onChange={(event) => setMouthshutUrl(event.target.value)} placeholder="mouthshut.com/product-reviews/..." /></label> : null}
          </div>
          <div className="onboarding-actions split-actions">
            <button type="button" className="secondary-button" onClick={() => setStep(1)}><ArrowLeft size={17} /> Back</button>
            <div><small>{selectedLabels.join(" · ")}</small><button className="primary-button" disabled={busy || !selectedSources.length}>{busy ? "Starting..." : "Start analysis"}<ArrowRight size={17} /></button></div>
          </div>
        </form>
      )}
      {error ? <p className="error onboarding-error">{error}</p> : null}
    </section>
  );
}
