import { SEVERITY, severityFor } from "../lib/format";

export function SeverityBadge({ score, className = "" }) {
  const key = severityFor(score);
  const meta = SEVERITY[key];
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ${meta.chip} ${className}`}
    >
      {meta.label}
    </span>
  );
}

/** Score bar + numeric value -- the row-level severity indicator. */
export function ScoreBar({ score }) {
  const key = severityFor(score);
  const meta = SEVERITY[key];
  const pct = Math.max(2, Math.min(100, score ?? 0));
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-24 overflow-hidden rounded-full bg-slate-100">
        <div className={`h-full rounded-full ${meta.bar}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-8 text-right text-xs font-semibold tabular-nums text-slate-700">
        {score === null || score === undefined ? "—" : Math.round(score)}
      </span>
    </div>
  );
}
