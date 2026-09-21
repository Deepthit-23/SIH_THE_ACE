import { SEVERITY, severityFor } from "../lib/format";

/** Tier label as a marked chip: a 3px tier rule and a light tint, ink text. */
export function SeverityBadge({ score, className = "" }) {
  const meta = SEVERITY[severityFor(score)];
  return <span className={`inline-block px-2 py-0.5 text-xs font-medium ${meta.chip} ${className}`}>{meta.label}</span>;
}

/** Row-level indicator: the score as a figure, with a thin bar in the tier colour beneath it. */
export function ScoreBar({ score }) {
  const meta = SEVERITY[severityFor(score)];
  const has = score !== null && score !== undefined;
  const pct = Math.max(2, Math.min(100, score ?? 0));
  return (
    <div className="w-16">
      <p className={`fig text-base font-semibold leading-none ${meta.text}`}>{has ? Math.round(score) : "-"}</p>
      <div className="mt-1.5 h-[3px] w-full bg-hairline">
        <div className={`h-full ${meta.bar}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
