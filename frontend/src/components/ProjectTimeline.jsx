// Horizontal lifecycle of one project, built only from dates already stored:
//   recommended -> completed -> first flagged by the engine -> case reviewed.
// Nodes are evenly spaced (readable when two events are days apart); the real elapsed time
// is written on each connector. Absent events are shown as dashed placeholders only where
// their absence means something (no completion on a recommended work, no review yet).

const MS_DAY = 86_400_000;

function toDate(v) {
  if (!v) return null;
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? null : d;
}

// Date-only fields ("2026-09-01") are calendar dates: show them as-is (UTC), never shifted by the
// viewer's timezone. Timestamps (scoring runs, case decisions) are instants: show them in local time,
// the same as the case panel does.
const isDateOnly = (v) => typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v);
function fmt(d, dateOnly = false) {
  return d.toLocaleDateString("en-GB", {
    day: "2-digit", month: "short", year: "numeric", ...(dateOnly ? { timeZone: "UTC" } : {}),
  });
}

export function elapsed(a, b) {
  const days = Math.round(Math.abs(b - a) / MS_DAY);
  if (days === 0) return "same day";
  if (days < 60) return `${days} day${days === 1 ? "" : "s"}`;
  if (days < 730) return `${Math.round(days / 30.44)} months`;
  return `${(days / 365.25).toFixed(1)} years`;
}

const TONE = {
  slate: { dot: "bg-ink border-ink-faint", text: "text-ink" },
  green: { dot: "bg-low border-low/40", text: "text-low" },
  red: { dot: "bg-high border-high/40", text: "text-high" },
  amber: { dot: "bg-medium border-medium/40", text: "text-ink" },
  indigo: { dot: "bg-ink-soft border-ink/20", text: "text-ink-soft" },
};

/** Build the ordered event list from a project-detail payload. Exported for testing. */
export function buildTimeline(p) {
  const flagTone = p.combined_risk_score >= 70 ? "red" : p.combined_risk_score >= 50 ? "amber" : "slate";
  const events = [];
  const rec = toDate(p.recommendation_date);
  const done = toDate(p.completion_date);
  const first = toDate(p.first_flagged_at || p.flagged_at);
  const latest = toDate(p.flagged_at);
  const review = p.case_status && p.case_status !== "pending" ? toDate(p.case_updated_at) : null;

  if (rec) events.push({ key: "rec", label: "Recommended", date: rec, dateOnly: isDateOnly(p.recommendation_date), tone: "slate", order: 0 });
  if (done) events.push({ key: "done", label: "Completed", date: done, dateOnly: isDateOnly(p.completion_date), tone: "green", order: 1 });
  else if (p.status === "recommended") events.push({ key: "done", label: "Completed", date: null, missing: "no completion recorded", order: 1 });
  if (first) {
    const rescored = latest && fmt(latest) !== fmt(first);
    events.push({
      key: "flag", label: "First flagged", date: first, tone: flagTone, order: 2,
      note: rescored ? `re-scored ${fmt(latest)}` : null,
    });
  }
  if (review) {
    events.push({ key: "case", label: `Case ${String(p.case_status).replace("_", " ")}`, date: review, tone: "indigo", order: 3 });
  } else {
    events.push({ key: "case", label: "Case review", date: null, missing: "not yet reviewed", order: 3 });
  }
  // chronological among dated events; placeholders keep their conceptual slot
  const dated = events.filter((e) => e.date).sort((a, b) => a.date - b.date || a.order - b.order);
  const out = [];
  let di = 0;
  for (const e of events.slice().sort((a, b) => a.order - b.order)) {
    out.push(e.date ? dated[di++] : e);
  }
  // keep placeholders after the dated events they logically follow
  return [...out.filter((e) => e.date), ...out.filter((e) => !e.date)];
}

export default function ProjectTimeline({ project }) {
  const events = buildTimeline(project);
  if (events.filter((e) => e.date).length === 0) return null;

  return (
    <div className="rounded border border-hairline bg-surface p-5">
      <h3 className="text-sm font-semibold text-ink">Project timeline</h3>
      <p className="mb-4 mt-1 text-xs text-ink-soft">
        Dates recorded for this work, with the time between each step. “First flagged” is the first
        scoring run on record; later runs re-score but do not move it.
      </p>
      <div className="overflow-x-auto pb-1">
        <ol className="flex min-w-[36rem] items-start" data-testid="project-timeline">
          {events.map((e, i) => {
            const t = TONE[e.tone] || TONE.slate;
            const prev = events[i - 1];
            return (
              <li key={e.key} className="min-w-[9rem] flex-1 last:w-36 last:flex-none">
                {/* node */}
                <div className="pr-2">
                  <div className="flex items-center">
                    <span
                      className={`h-3 w-3 shrink-0 rounded-full border-2 ${
                        e.date ? t.dot : "border-dashed border-hairline bg-surface"
                      }`}
                    />
                    {i < events.length - 1 && (
                      <span className={`ml-1 h-0 flex-1 border-t-2 ${
                        events[i + 1].date && e.date ? "border-hairline" : "border-dashed border-hairline"
                      }`} />
                    )}
                  </div>
                  <p className={`mt-2 text-xs font-semibold ${e.date ? t.text : "text-ink-faint"}`}>
                    {e.label}
                  </p>
                  {e.date ? (
                    <p className="text-sm text-ink" title={e.date.toISOString()}>{fmt(e.date, e.dateOnly)}</p>
                  ) : (
                    <p className="text-xs italic text-ink-faint">{e.missing}</p>
                  )}
                  {e.note && <p className="text-[11px] text-ink-faint">{e.note}</p>}
                  {e.date && prev?.date && (
                    <p className="text-[11px] text-ink-faint">+{elapsed(prev.date, e.date)}</p>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}
