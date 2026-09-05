// Display helpers -- never render "null"/"undefined"/"(unknown)" to the user.

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
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
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

export const SEVERITY = {
  high: {
    label: "High",
    bar: "bg-red-600",
    chip: "bg-red-50 text-red-700 ring-1 ring-inset ring-red-600/20",
    fill: "#dc2626",
  },
  medium: {
    label: "Medium",
    bar: "bg-amber-500",
    chip: "bg-amber-50 text-amber-800 ring-1 ring-inset ring-amber-600/20",
    fill: "#f59e0b",
  },
  low: {
    label: "Low",
    bar: "bg-yellow-400",
    chip: "bg-yellow-50 text-yellow-800 ring-1 ring-inset ring-yellow-600/20",
    fill: "#facc15",
  },
  none: {
    label: "Clear",
    bar: "bg-slate-300",
    chip: "bg-slate-100 text-slate-600 ring-1 ring-inset ring-slate-500/20",
    fill: "#cbd5e1",
  },
  unscored: {
    label: "Unscored",
    bar: "bg-slate-200",
    chip: "bg-slate-100 text-slate-500 ring-1 ring-inset ring-slate-400/20",
    fill: "#e2e8f0",
  },
};

export function titleCase(s) {
  return text(s, "")
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}
