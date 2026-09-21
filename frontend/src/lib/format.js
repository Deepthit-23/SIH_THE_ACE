// Display helpers -- never render "null"/"undefined"/"(unknown)" to the user.
import { T } from "./tokens";

export function text(value, fallback = "—") {
  if (value === null || value === undefined) return fallback;
  const s = String(value).trim();
  if (!s || s.toLowerCase() === "null" || s === "(unknown)") return fallback;
  return s;
}

export function formatINR(value) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  if (n >= 1e7) return `₹${(n / 1e7).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} Cr`;
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`;
  return `₹${n.toLocaleString("en-IN")}`;
}

export function severityFor(score) {
  if (score === null || score === undefined) return "unscored";
  if (score >= 70) return "high";
  if (score >= 50) return "medium";
  if (score > 0) return "low";
  return "none";
}

// Risk tiers. A tier is shown as a MARK (a bar, or a 3px rule on a chip), tinted lightly behind it; the label
// text stays ink because the medium tier (about 3.2:1 on white) is too pale to carry small text.
export const SEVERITY = {
  high: {
    label: "High",
    bar: "bg-high",
    chip: "border-l-[3px] border-high bg-high/10 text-ink",
    text: "text-high",
    fill: T.high,
  },
  medium: {
    label: "Medium",
    bar: "bg-medium",
    chip: "border-l-[3px] border-medium bg-medium/10 text-ink",
    text: "text-ink",
    fill: T.medium,
  },
  low: {
    label: "Low",
    bar: "bg-low",
    chip: "border-l-[3px] border-low bg-low/10 text-ink",
    text: "text-low",
    fill: T.low,
  },
  none: {
    label: "Clear",
    bar: "bg-clear",
    chip: "border-l-[3px] border-clear bg-clear/10 text-ink-soft",
    text: "text-ink-soft",
    fill: T.clear,
  },
  unscored: {
    label: "Unscored",
    bar: "bg-hairline",
    chip: "border-l-[3px] border-hairline bg-canvas text-ink-soft",
    text: "text-ink-faint",
    fill: T.hairline,
  },
};

export function titleCase(s) {
  return text(s, "")
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export const CASE_STATUS = {
  pending: { label: "Pending", chip: "border-l-[3px] border-clear bg-clear/10 text-ink-soft" },
  under_review: { label: "Under review", chip: "border-l-[3px] border-accent bg-accent/10 text-ink" },
  confirmed: { label: "Confirmed", chip: "border-l-[3px] border-high bg-high/10 text-ink" },
  dismissed: { label: "Dismissed", chip: "border-l-[3px] border-low bg-low/10 text-ink" },
};

export const CASE_ORDER = ["pending", "under_review", "confirmed", "dismissed"];

export function fmtDateTime(v) {
  if (!v) return "—";
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
}
