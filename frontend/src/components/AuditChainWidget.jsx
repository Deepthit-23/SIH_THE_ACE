import { useEffect, useState } from "react";
import { api } from "../api/client";

// The audit log is a hash chain: each entry stores the hash of the one before it, so changing any past
// entry breaks every link after it. This widget draws the newest few entries as linked blocks. It is a
// picture of the chain's *structure* (and refreshes as entries are appended); the pass/fail verdict over
// the WHOLE chain stays with the "Audit trail verified" badge in the header.

const KIND = {
  risk_score: { label: "score", dot: "bg-ink-soft" },
  case_review: { label: "case", dot: "bg-ink-soft" },
  admin_action: { label: "admin", dot: "bg-medium" },
};

export const short = (h) => (h ? `${h.slice(0, 6)}…${h.slice(-4)}` : "—");

function when(ts) {
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("en-GB", {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

/** For newest-first entries: does each entry's previous_hash equal the next one's hash? */
export function linkStates(entries) {
  return entries.map((e, i) => (i === entries.length - 1 ? null : e.previous_hash === entries[i + 1].hash));
}

export default function AuditChainWidget({ limit = 5, pollMs = 20000 }) {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = () =>
      api.auditRecent(limit).then((d) => alive && (setData(d), setFailed(false))).catch(() => alive && setFailed(true));
    load();
    const t = setInterval(load, pollMs);
    return () => { alive = false; clearInterval(t); };
  }, [limit, pollMs]);

  if (failed && !data) return null;          // stay quiet if the feed is unavailable
  if (!data) return <div className="h-40 border border-hairline" />;

  const links = linkStates(data.entries);
  return (
    <section aria-label="Audit chain, latest entries" data-testid="audit-chain">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="text-xs font-semibold text-ink">Audit chain</h2>
        <span className="fig text-[11px] text-ink-faint">height {data.height.toLocaleString("en-IN")}</span>
      </div>
      {/* the chain as one vertical line: each entry hangs off it, and the line is what links them */}
      <ol className="ml-[3px]">
        {data.entries.map((e, i) => {
          const k = KIND[e.event_type] || { label: e.event_type, dot: "bg-clear" };
          const linked = links[i] !== false;
          return (
            <li key={e.id} className={`relative pb-3 pl-4 ${i === data.entries.length - 1 ? "" : `border-l ${linked ? "border-ink-faint" : "border-high"}`}`}
              title={`hash ${e.hash}\nprevious ${e.previous_hash}${linked ? "" : "\nlink broken"}`}>
              <span className={`absolute -left-[3.5px] top-1 h-[7px] w-[7px] rounded-full ${k.dot}`} />
              <p className="flex items-baseline justify-between text-[11px]">
                <span className="font-medium text-ink-soft">{k.label}</span>
                <span className="fig text-ink-faint">{e.id.toLocaleString("en-IN")}</span>
              </p>
              <p className="fig text-xs text-ink">{short(e.hash)}</p>
              <p className="text-[11px] text-ink-faint">{when(e.timestamp)}</p>
            </li>
          );
        })}
      </ol>
      <p className="text-[11px] leading-snug text-ink-faint">
        Each entry holds the hash of the one below it. Edit any past entry and every link above it breaks.
      </p>
    </section>
  );
}
