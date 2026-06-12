import { Bar, Doughnut, Line } from "react-chartjs-2";
import type { Results } from "../lib/api";

const palette = ["#00685f", "#2f6fed", "#d77a2b", "#6d4aff", "#c44536", "#108a51", "#a53d74", "#5a6673"];

function entries(obj?: Record<string, number>) {
  return Object.entries(obj || {}).filter(([, value]) => Number(value) > 0);
}

function humanizeTheme(theme: string) {
  if (theme === "other") return "Other";
  if (theme === "payments_or_refunds") return "Payments & refunds.";
  if (theme === "unfair_refund_policies_and_failure_to_process_refunds") {
    return "Refunds: unfair policies & failures to process.";
  }
  return theme.replaceAll("_", " ");
}

export function ResultsCharts({ results }: { results: Results }) {
  const themes = results.themes.slice(0, 10);
  const bucketEntries = entries(results.summary.bucket_split);
  const ratingEntries = entries(results.summary.rating_distribution);
  const sourceEntries = entries(results.summary.source_mix);
  const volumeEntries = entries(results.summary.volume_over_time);
  const sourceQuality = (results.summary.source_quality || []) as Array<{ source: string; rows: number; useful_rows: number; non_other_pct: number }>;

  return (
    <div className="chart-grid">
      <section className="section-block chart-panel wide-chart">
        <h3>Themes by score</h3>
        <Bar
          data={{
            labels: themes.map((theme) => humanizeTheme(theme.theme)),
            datasets: [{ label: "Theme score", data: themes.map((theme) => theme.theme_score), backgroundColor: palette[0] }],
          }}
          options={{
            indexAxis: "y",
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
          }}
        />
      </section>
      <section className="section-block chart-panel">
        <h3>Bucket split</h3>
        <Doughnut
          data={{
            labels: bucketEntries.map(([key]) => key),
            datasets: [{ data: bucketEntries.map(([, value]) => value), backgroundColor: palette.slice(1) }],
          }}
          options={{ responsive: true, maintainAspectRatio: false }}
        />
      </section>
      <section className="section-block chart-panel">
        <h3>Rating mix</h3>
        <Bar
          data={{
            labels: ratingEntries.map(([key]) => `${key} star`),
            datasets: [{ label: "Reviews", data: ratingEntries.map(([, value]) => value), backgroundColor: palette[2] }],
          }}
          options={{ responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } }}
        />
      </section>
      <section className="section-block chart-panel">
        <h3>Source mix</h3>
        <Doughnut
          data={{ labels: sourceEntries.map(([key]) => key), datasets: [{ data: sourceEntries.map(([, value]) => value), backgroundColor: palette }] }}
          options={{ responsive: true, maintainAspectRatio: false }}
        />
      </section>
      <section className="section-block chart-panel">
        <h3>Volume over time</h3>
        <Line
          data={{
            labels: volumeEntries.map(([key]) => key),
            datasets: [{ label: "Reviews", data: volumeEntries.map(([, value]) => value), borderColor: palette[1], backgroundColor: "#dbeafe" }],
          }}
          options={{ responsive: true, maintainAspectRatio: false }}
        />
      </section>
      <section className="section-block chart-panel source-roi-chart">
        <h3>Useful rows by source</h3>
        <Bar
          data={{
            labels: sourceQuality.map((row) => row.source),
            datasets: [
              { label: "Useful rows", data: sourceQuality.map((row) => row.useful_rows), backgroundColor: palette[0] },
              { label: "Total rows", data: sourceQuality.map((row) => row.rows), backgroundColor: "#b9c7c4" },
            ],
          }}
          options={{ responsive: true, maintainAspectRatio: false }}
        />
      </section>
    </div>
  );
}
