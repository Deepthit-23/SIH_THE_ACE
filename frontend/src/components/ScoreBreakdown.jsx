import { severityFor, SEVERITY } from "../lib/format";

const RULE_FILL = {
  cost_anomaly: "#475569",
  contractor_concentration: "#64748b",
  payment_gap: "#94a3b8",
  stalled_project: "#cbd5e1",
};
const ML_FILL = "#6366f1";

/**
 * Visual decomposition of the 0–100 score: one segment per triggered rule
 * (width = its point weight) plus the model's contribution. Reinforces
 * "explainable, not a black box".
 */
export default function ScoreBreakdown({ explanation = [], ruleScore, mlScore, combined }) {
  const segs = explanation
    .map((e) => ({
      key: e.code,
      label: e.label,
      source: e.source,
      weight: Math.max(0, Number(e.weight) || 0),
      fill: e.source === "ml" ? ML_FILL : RULE_FILL[e.code] || "#94a3b8",
    }))
    .filter((s) => s.weight > 0);

  const total = segs.reduce((a, s) => a + s.weight, 0);
  if (total === 0) return null;

  const meta = SEVERITY[severityFor(combined)];

  return (
    <div className="rounded border border-slate-200 bg-white p-5">
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-slate-800">How the score is built</h3>
        <span className="text-xs text-slate-500">
          rule signal {Math.round(ruleScore ?? 0)} · model {Math.round(mlScore ?? 0)} →{" "}
          <span className="font-semibold" style={{ color: meta.fill }}>
            {Math.round(combined ?? 0)}
          </span>
        </span>
      </div>

      <div className="mt-3 flex h-5 w-full overflow-hidden rounded bg-slate-100">
        {segs.map((s, i) => (
          <div
            key={i}
            style={{ width: `${(s.weight / total) * 100}%`, backgroundColor: s.fill }}
            title={`${s.label}: ${Math.round(s.weight)}`}
          />
        ))}
      </div>

      <ul className="mt-3 space-y-1">
        {segs.map((s, i) => (
          <li key={i} className="flex items-center justify-between text-xs">
            <span className="flex items-center gap-2 text-slate-600">
              <span className="h-2 w-2 rounded-sm" style={{ backgroundColor: s.fill }} />
              {s.label}
              {s.source === "ml" && <span className="text-slate-400">(anomaly model)</span>}
            </span>
            <span className="tabular-nums text-slate-500">{Math.round(s.weight)}</span>
          </li>
        ))}
      </ul>

      <p className="mt-2 text-[11px] leading-relaxed text-slate-400">
        Rule weights are fixed points per rule; the model's share rises only for
        genuine statistical outliers. The combined score then applies a
        diminishing-returns curve, so stacking signals can't trivially pin a
        project at 100.
      </p>
    </div>
  );
}
