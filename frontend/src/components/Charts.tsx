import { Bar, Doughnut, Line } from "react-chartjs-2";
import type { Results } from "../lib/api";

const palette = ["#00685f", "#2f6fed", "#d77a2b", "#6d4aff", "#c44536", "#108a51", "#a53d74", "#5a6673"];

function entries(obj?: Record<string, number>) {
  return Object.entries(obj || {}).filter(([, value]) => Number(value) > 0);
}

function formatSource(source: string) {
  const labels: Record<string, string> = {
    play: "Google Play",
    appstore: "App Store",
    maps: "Google Maps",
    instagram: "Instagram",
    twitter: "X / Twitter",
    reddit: "Reddit",
    mouthshut: "MouthShut",
  };
  return labels[source] || source;
}

const compactOptions = {
  responsive: true,
  maintainAspectRatio: false,
  resizeDelay: 150,
  animation: false as const,
};

export function ResultsCharts({ results }: { results: Results }) {
  const ratingEntries = entries(results.summary.rating_distribution);
  const sourceEntries = entries(results.summary.source_mix);
  const volumeEntries = entries(results.summary.volume_over_time);
  const sourceQuality = Array.isArray(results.summary.source_quality)
    ? results.summary.source_quality as Array<{ source: string; rows: number; useful_rows: number; non_other_pct?: number }>
    : [];
  const sourceYield = sourceQuality
    .filter((row) => typeof row.non_other_pct === "number" && Number.isFinite(row.non_other_pct) && Number(row.rows) > 0)
    .map((row) => ({ source: formatSource(row.source), yield: Number(row.non_other_pct) * 100 }))
    .sort((a, b) => b.yield - a.yield);
  const hasSourceComparison = sourceQuality.length > 1 || sourceEntries.length > 1;
  const hasSourceYield = sourceYield.length > 0;
  const hasVolumeTrend = volumeEntries.length > 1;
  const hasRatings = ratingEntries.length > 0;
  const panelCount = [hasRatings, hasVolumeTrend, hasSourceComparison, hasSourceYield].filter(Boolean).length;

  if (!panelCount) return null;

  return (
    <section className="section-block feedback-patterns">
      <div className="section-title-row">
        <div><h2>Feedback patterns</h2><p>See the feedback mix, momentum, source contribution, and which listening posts return the most actionable signal.</p></div>
      </div>
      <div className={"chart-grid compact-chart-grid panels-" + panelCount}>
        {hasRatings ? (
          <section className="chart-panel">
            <h3>Rating mix</h3>
            <div className="chart-canvas">
              <Bar
                data={{ labels: ratingEntries.map(([key]) => `${key} star`), datasets: [{ label: "Selected reviews", data: ratingEntries.map(([, value]) => value), backgroundColor: palette[2] }] }}
                options={{ ...compactOptions, plugins: { legend: { display: false } } }}
              />
            </div>
          </section>
        ) : null}
        {hasVolumeTrend ? (
          <section className="chart-panel">
            <h3>Feedback volume over time</h3>
            <div className="chart-canvas">
              <Line
                data={{ labels: volumeEntries.map(([key]) => key), datasets: [{ label: "Selected reviews", data: volumeEntries.map(([, value]) => value), borderColor: palette[1], backgroundColor: "#dbeafe", tension: 0.25, fill: true }] }}
                options={{ ...compactOptions, plugins: { legend: { display: false } } }}
              />
            </div>
          </section>
        ) : null}
        {hasSourceComparison ? (
          <section className="chart-panel">
            <h3>Source contribution</h3>
            <div className="chart-canvas">
              {sourceQuality.length > 1 ? (
                <Bar
                  data={{ labels: sourceQuality.map((row) => formatSource(row.source)), datasets: [{ label: "Useful feedback", data: sourceQuality.map((row) => row.useful_rows), backgroundColor: palette[0] }, { label: "Selected feedback", data: sourceQuality.map((row) => row.rows), backgroundColor: "#b9c7c4" }] }}
                  options={compactOptions}
                />
              ) : (
                <Doughnut
                  data={{ labels: sourceEntries.map(([key]) => formatSource(key)), datasets: [{ data: sourceEntries.map(([, value]) => value), backgroundColor: palette }] }}
                  options={compactOptions}
                />
              )}
            </div>
          </section>
        ) : null}
        {hasSourceYield ? (
          <section className="chart-panel">
            <h3>Actionable signal yield by source</h3>
            <p>Share of feedback mapped to a specific issue theme; higher yield means a more actionable listening post.</p>
            <div className="chart-canvas" style={{ height: Math.max(210, Math.min(340, sourceYield.length * 44)) }}>
              <Bar
                data={{
                  labels: sourceYield.map((row) => row.source),
                  datasets: [{ label: "Actionable feedback", data: sourceYield.map((row) => row.yield), backgroundColor: palette[0] }],
                }}
                options={{
                  ...compactOptions,
                  indexAxis: "y" as const,
                  plugins: { legend: { display: false } },
                  scales: { x: { min: 0, max: 100, ticks: { stepSize: 25, callback: (value) => `${value}%` } } },
                }}
              />
            </div>
          </section>
        ) : null}
      </div>
    </section>
  );
}
