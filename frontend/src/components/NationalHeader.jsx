import { api } from "../api/client";
import { useAsync } from "../hooks/useAsync";
import { formatINR } from "../lib/format";

function Tile({ label, value, sub }) {
  return (
    <div className="min-w-[9rem] flex-1 border-r border-slate-200 px-4 py-2 last:border-r-0">
      <p className="text-[11px] uppercase tracking-wide text-slate-400">{label}</p>
      <p className="text-lg font-semibold text-slate-800">{value}</p>
      {sub && <p className="text-[11px] text-slate-500">{sub}</p>}
    </div>
  );
}

/** Landing strip: national MPLAD figures, above the ranked list. */
export default function NationalHeader() {
  const { status, data } = useAsync(() => api.summary(), []);
  if (status !== "success" || !data) {
    return <div className="h-16 rounded border border-slate-200 bg-white" />;
  }
  const pct = (v) => (v === null || v === undefined ? "—" : `${v}%`);
  const n = (v) => Number(v || 0).toLocaleString("en-IN");
  return (
    <div className="flex flex-wrap items-stretch rounded border border-slate-200 bg-white">
      <Tile label="Allocated (MPLADS)" value={formatINR(data.allocated_amount)} sub={`${data.mps} MPs`} />
      <Tile label="Recommended" value={formatINR(data.recommended_amount)} sub={`${n(data.recommended_works)} works`} />
      <Tile label="Spent" value={formatINR(data.total_expenditure)} sub={`${pct(data.spend_pct_of_allocation)} of allocation`} />
      <Tile label="Completion rate" value={pct(data.completion_rate_pct)} sub={`${n(data.completed_works)} completed`} />
      <Tile
        label="Flagged for review"
        value={n(data.flagged_high + data.flagged_medium)}
        sub={`${n(data.flagged_high)} high · of ${n(data.projects_scored)} scored`}
      />
    </div>
  );
}
