import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../hooks/useAsync";
import { ScoreBar } from "../components/Severity";
import { Empty, ErrorBox, Loading } from "../components/StateMessage";
import { formatINR, text, titleCase } from "../lib/format";

const WINDOWS = [30, 90, 180];

/** Newly recorded works (last N days of the data) that already score as medium/high risk and
 *  have not been reviewed yet. Scoped server-side to the signed-in user's state/district/MP. */
export default function EarlyWarningPage({ role }) {
  const navigate = useNavigate();
  const [days, setDays] = useState(90);
  const params = useMemo(
    () => ({ recent_days: days, min_score: 50, case_status: "pending", limit: 50, sort_by: "risk", order: "desc" }),
    [days],
  );
  const { status, data, error, reload } = useAsync(() => api.riskScores(params), [params]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold">Early warning</h2>
          <p className="text-sm text-slate-500">
            {role === "mp_self"
              ? "Recent works in your portfolio that already look unusual."
              : "Recently recorded works that already score medium or high and are still awaiting review."}
          </p>
        </div>
        <label className="flex items-center gap-2 text-xs text-slate-500">
          Window
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="rounded border border-slate-300 bg-white px-2 py-1.5 text-sm"
          >
            {WINDOWS.map((d) => (
              <option key={d} value={d}>Last {d} days</option>
            ))}
          </select>
        </label>
      </div>

      {status === "loading" && <Loading label="Looking for new flags…" />}
      {status === "error" && <ErrorBox error={error} onRetry={reload} />}
      {status === "success" && data.items.length === 0 && (
        <Empty>No unreviewed medium/high flags on works from the last {days} days.</Empty>
      )}
      {status === "success" && data.items.length > 0 && (
        <>
          <p className="text-sm text-slate-600">
            <span className="font-semibold">{data.total.toLocaleString()}</span> new flag{data.total === 1 ? "" : "s"}
            {data.total > data.items.length && ` (showing the top ${data.items.length})`}
          </p>
          <ul className="divide-y divide-slate-100 rounded border border-slate-200 bg-white">
            {data.items.map((p) => (
              <li key={p.id} onClick={() => navigate(`/projects/${p.id}`)} className="flex cursor-pointer gap-4 px-4 py-3 hover:bg-slate-50">
                <div className="w-36 shrink-0"><ScoreBar score={p.combined_risk_score} /></div>
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium text-slate-800">{text(p.work_description, "Untitled work")}</p>
                  <p className="text-xs text-slate-500">
                    {text(p.mp_name)} · {text(p.district)}, {text(p.state)} · {titleCase(p.status)} · {formatINR(p.amount)}
                  </p>
                  {p.top_reasons?.length > 0 && <p className="mt-0.5 truncate text-xs text-slate-500">{p.top_reasons.join("  ·  ")}</p>}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
