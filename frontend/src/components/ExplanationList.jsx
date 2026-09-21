import { SEVERITY, severityFor } from "../lib/format";

/**
 * Renders the ordered explanation list, grouped into rule-based findings and
 * the anomaly-model signal. Each reason reads as a standalone sentence.
 */
export default function ExplanationList({ items }) {
  if (!items || items.length === 0) {
    return (
      <p className="text-sm text-ink-soft">
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
          <h4 className="mb-2 text-xs font-semibold text-ink-soft">
            Rule-based findings
          </h4>
          <ul className="space-y-2">
            {rules.map((e, i) => (
              <li
                key={i}
                className="flex gap-3 rounded border border-hairline bg-surface p-3"
              >
                <span className="mt-0.5 h-2 w-2 shrink-0 rounded-full bg-clear" />
                <div>
                  <p className="text-sm text-ink">{e.message}</p>
                  <p className="mt-0.5 text-xs text-ink-faint">{e.label}</p>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {ml.length > 0 && (
        <section>
          <h4 className="mb-2 text-xs font-semibold text-ink-soft">
            Anomaly-model signal
          </h4>
          <ul className="space-y-2">
            {ml.map((e, i) => (
              <li
                key={i}
                className="flex gap-3 rounded border border-ink/15 bg-ink/5 p-3"
              >
                <span className="mt-0.5 h-2 w-2 shrink-0 rounded-full bg-ink-soft" />
                <p className="text-sm text-ink">{e.message}</p>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-ink-faint">
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
    <div className="border-l-[3px] pl-4" style={{ borderColor: meta.fill }}>
      <p className={`fig text-[40px] font-semibold leading-none ${meta.text}`}>
        {score === null || score === undefined ? "-" : Math.round(score)}
      </p>
      <p className="mt-1.5 text-sm font-semibold">{meta.label} risk</p>
      <p className="text-xs text-ink-soft">combined score, out of 100</p>
    </div>
  );
}
