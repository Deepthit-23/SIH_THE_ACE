import { severityFor, SEVERITY } from "../lib/format";
import { T } from "../lib/tokens";

// Rule signals in ink shades, the anomaly model in the neutral warm grey, so the two sources read apart.
const RULE_FILL = {
  cost_anomaly: T.ink,
  contractor_concentration: T.inkSoft,
  payment_gap: T.inkFaint,
  stalled_project: T.hairline,
};
const ML_FILL = T.clear;

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
      fill: e.source === "ml" ? ML_FILL : RULE_FILL[e.code] || T.inkFaint,
    }))
    .filter((s) => s.weight > 0);

  const total = segs.reduce((a, s) => a + s.weight, 0);
  if (total === 0) return null;

  const meta = SEVERITY[severityFor(combined)];

  return (
    <div className="rounded border border-hairline bg-surface p-5">
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-ink">How the score is built</h3>
        <span className="text-xs text-ink-soft">
          rule signal <span className="fig">{Math.round(ruleScore ?? 0)}</span>, model{" "}
          <span className="fig">{Math.round(mlScore ?? 0)}</span>, combined{" "}
          <span className={`fig font-semibold ${meta.text}`}>{Math.round(combined ?? 0)}</span>
        </span>
      </div>

      <div className="mt-3 flex h-5 w-full overflow-hidden rounded bg-canvas">
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
            <span className="flex items-center gap-2 text-ink-soft">
              <span className="h-2 w-2 rounded-sm" style={{ backgroundColor: s.fill }} />
              {s.label}
              {s.source === "ml" && <span className="text-ink-faint">(anomaly model)</span>}
            </span>
            <span className="tabular-nums text-ink-soft">{Math.round(s.weight)}</span>
          </li>
        ))}
      </ul>

      <p className="mt-2 text-[11px] leading-relaxed text-ink-faint">
        Rule weights are fixed points per rule; the model's share rises only for
        genuine statistical outliers. The combined score then applies a
        diminishing-returns curve, so stacking signals can't trivially pin a
        project at 100.
      </p>
    </div>
  );
}
