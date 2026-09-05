import { SEVERITY, severityFor } from "../lib/format";

/**
 * Renders the ordered explanation list, grouped into rule-based findings and
 * the anomaly-model signal. Each reason reads as a standalone sentence.
 */
export default function ExplanationList({ items }) {
  if (!items || items.length === 0) {
    return (
      <p className="text-sm text-slate-500">
        No risk signals triggered for this project.
      </p>
    );
  }

  const rules = items.filter((e) => e.source === "rule");
  const ml = items.filter((e) => e.source === "ml");

  return (
    <div className="space-y-5">
      {rules.length > 0 && (
        <section>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Rule-based findings
          </h4>
          <ul className="space-y-2">
            {rules.map((e, i) => (
              <li
                key={i}
                className="flex gap-3 rounded border border-slate-200 bg-white p-3"
              >
                <span className="mt-0.5 h-2 w-2 shrink-0 rounded-full bg-slate-400" />
                <div>
                  <p className="text-sm text-slate-800">{e.message}</p>
                  <p className="mt-0.5 text-xs text-slate-400">{e.label}</p>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {ml.length > 0 && (
        <section>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Anomaly-model signal
          </h4>
          <ul className="space-y-2">
            {ml.map((e, i) => (
              <li
                key={i}
                className="flex gap-3 rounded border border-indigo-100 bg-indigo-50/50 p-3"
              >
                <span className="mt-0.5 h-2 w-2 shrink-0 rounded-full bg-indigo-400" />
                <p className="text-sm text-slate-800">{e.message}</p>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-slate-400">
            The model compares this project against ~131,000 others on cost,
            vendor concentration, payment status and timeline. It is unsupervised
            — it learns "typical" from the data itself.
          </p>
        </section>
      )}
    </div>
  );
}

export function ScoreHeadline({ score }) {
  const meta = SEVERITY[severityFor(score)];
  return (
    <div className="flex items-center gap-3">
      <div
        className="flex h-14 w-14 items-center justify-center rounded-lg text-xl font-bold text-white"
        style={{ backgroundColor: meta.fill }}
      >
        {score === null || score === undefined ? "—" : Math.round(score)}
      </div>
      <div>
        <p className="text-sm font-semibold text-slate-800">{meta.label} risk</p>
        <p className="text-xs text-slate-500">combined risk score / 100</p>
      </div>
    </div>
  );
}
