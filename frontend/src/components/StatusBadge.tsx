import { AlertTriangle, CheckCircle2, Clock3, Loader2, XCircle } from "lucide-react";
import type { Run } from "../lib/api";

const LABELS: Record<Run["status"], string> = {
  queued: "Queued",
  scraping: "Scraping",
  classifying: "Classifying",
  done: "Done",
  partial: "Partial",
  failed: "Failed",
};

export function StatusBadge({ status }: { status: Run["status"] }) {
  const Icon = status === "done" ? CheckCircle2 : status === "failed" ? XCircle : status === "partial" ? AlertTriangle : status === "queued" ? Clock3 : Loader2;
  return (
    <span className={`status status-${status}`}>
      <Icon size={14} className={status === "scraping" || status === "classifying" ? "spin" : ""} />
      {LABELS[status]}
    </span>
  );
}

