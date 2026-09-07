import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../hooks/useAsync";
import { SeverityBadge } from "../components/Severity";
import { Empty, ErrorBox, Loading } from "../components/StateMessage";
import { CASE_STATUS, fmtDateTime, text } from "../lib/format";

const TABS = [
  { value: "", label: "All" },
  { value: "under_review", label: "Under review" },
  { value: "confirmed", label: "Confirmed" },
  { value: "dismissed", label: "Dismissed" },
];

export default function CasesPage() {
  const [tab, setTab] = useState("");
  const { status, data, error, reload } = useAsync(
    () => api.cases({ status: tab || undefined, limit: 200 }),
    [tab],
  );

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">Case log</h2>
        <p className="text-sm text-slate-500">
          Every flag an auditor has acted on. Dismissals record a reason — the
          feedback a production system would use to tune thresholds and retrain.
        </p>
      </div>

      <div className="flex gap-1 border-b border-slate-200">
        {TABS.map((t) => (
          <button
            key={t.value}
            onClick={() => setTab(t.value)}
            className={
              "px-3 py-1.5 text-sm " +
              (tab === t.value
                ? "border-b-2 border-slate-800 font-medium text-ink"
                : "text-slate-500 hover:text-ink")
            }
          >
            {t.label}
          </button>
        ))}
      </div>

      {status === "loading" && <Loading />}
      {status === "error" && <ErrorBox error={error} onRetry={reload} />}
      {status === "success" && data.items.length === 0 && (
        <Empty>No cases yet. Open a flagged project and set its status.</Empty>
      )}

      {status === "success" && data.items.length > 0 && (
        <div className="overflow-x-auto rounded border border-slate-200 bg-white">
          <table className="min-w-full text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Project</th>
                <th className="px-3 py-2">Risk</th>
                <th className="px-3 py-2">Note</th>
                <th className="px-3 py-2">Updated</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.items.map((c) => (
                <tr key={c.project_id} className="hover:bg-slate-50">
                  <td className="px-3 py-2.5">
                    <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${CASE_STATUS[c.status]?.chip || ""}`}>
                      {CASE_STATUS[c.status]?.label || c.status}
                    </span>
                  </td>
                  <td className="px-3 py-2.5">
                    <Link
                      to={`/projects/${c.project_id}`}
                      title={text(c.work_description, "")}
                      className="block max-w-[22rem] truncate font-medium text-slate-800 hover:underline"
                    >
                      {text(c.work_description, `Project ${c.project_id}`)}
                    </Link>
                    <p className="text-xs text-slate-400">{text(c.mp_name)}</p>
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5"><SeverityBadge score={c.combined_risk_score} /></td>
                  <td className="px-3 py-2.5 text-xs text-slate-600">
                    <span className="block max-w-[24rem] truncate" title={text(c.note, "")}>
                      {text(c.note, "—")}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-xs text-slate-400">{fmtDateTime(c.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
