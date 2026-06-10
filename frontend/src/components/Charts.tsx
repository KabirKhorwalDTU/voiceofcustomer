import { Bar, Doughnut, Line } from "react-chartjs-2";
import type { Results } from "../lib/api";

const palette = ["#0f766e", "#7c3aed", "#d97706", "#2563eb", "#dc2626", "#16a34a", "#be123c", "#4b5563"];

function entries(obj?: Record<string, number>) {
  return Object.entries(obj || {}).filter(([, value]) => Number(value) > 0);
}

export function ResultsCharts({ results }: { results: Results }) {
  const themes = results.themes.slice(0, 10);
  const bucketEntries = entries(results.summary.bucket_split);
  const severityEntries = entries(results.summary.severity_distribution);
  const sourceEntries = entries(results.summary.source_mix);
  const volumeEntries = entries(results.summary.volume_over_time);

  return (
    <div className="chart-grid">
      <section className="panel chart-panel">
        <h3>Themes By Score</h3>
        <Bar
          data={{
            labels: themes.map((theme) => theme.theme.replaceAll("_", " ")),
            datasets: [{ label: "Theme score", data: themes.map((theme) => theme.theme_score), backgroundColor: palette[0] }],
          }}
          options={{ indexAxis: "y", responsive: true, maintainAspectRatio: false }}
        />
      </section>
      <section className="panel chart-panel">
        <h3>Bucket Split</h3>
        <Doughnut
          data={{ labels: bucketEntries.map(([key]) => key), datasets: [{ data: bucketEntries.map(([, value]) => value), backgroundColor: palette.slice(1) }] }}
          options={{ responsive: true, maintainAspectRatio: false }}
        />
      </section>
      <section className="panel chart-panel">
        <h3>Severity</h3>
        <Bar
          data={{ labels: severityEntries.map(([key]) => `S${key}`), datasets: [{ label: "Reviews", data: severityEntries.map(([, value]) => value), backgroundColor: palette[2] }] }}
          options={{ responsive: true, maintainAspectRatio: false }}
        />
      </section>
      <section className="panel chart-panel">
        <h3>Volume Over Time</h3>
        <Line
          data={{ labels: volumeEntries.map(([key]) => key), datasets: [{ label: "Reviews", data: volumeEntries.map(([, value]) => value), borderColor: palette[3], backgroundColor: "#dbeafe" }] }}
          options={{ responsive: true, maintainAspectRatio: false }}
        />
      </section>
      <section className="panel chart-panel source-panel">
        <h3>Source Mix</h3>
        <Doughnut
          data={{ labels: sourceEntries.map(([key]) => key), datasets: [{ data: sourceEntries.map(([, value]) => value), backgroundColor: palette }] }}
          options={{ responsive: true, maintainAspectRatio: false }}
        />
      </section>
    </div>
  );
}
