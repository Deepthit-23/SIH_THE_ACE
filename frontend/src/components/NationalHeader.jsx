import { api } from "../api/client";
import { useAsync } from "../hooks/useAsync";
import { formatINR } from "../lib/format";

const n = (v) => Number(v || 0).toLocaleString("en-IN");
const pct = (v) => (v === null || v === undefined ? "-" : `${v}%`);

function Figure({ label, value, note, className = "" }) {
  return (
    <div className={`py-4 ${className}`}>
      <dt className="label">{label}</dt>
      <dd className="fig mt-1.5 text-[22px] font-medium leading-none">{value}</dd>
      {note && <p className="mt-1.5 text-xs text-ink-soft">{note}</p>}
    </div>
  );
}

/** What needs looking at. The one figure that asks for action gets the weight; the rest are context. */
function Flagged({ data, className = "" }) {
  return (
    <div className={`py-4 ${className}`}>
      <dt className="label">Flagged for review</dt>
      <dd className="fig mt-1.5 text-[34px] font-semibold leading-none">{n(data.flagged_high + data.flagged_medium)}</dd>
      <p className="mt-2 flex flex-wrap items-center gap-x-4 text-xs text-ink-soft">
        <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 bg-high" />{n(data.flagged_high)} high</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 bg-medium" />{n(data.flagged_medium)} medium</span>
        <span>of {n(data.projects_scored)} scored</span>
      </p>
    </div>
  );
}

/** National figures as one ruled ledger line above the list, not a row of cards. */
export default function NationalHeader() {
  const { status, data } = useAsync(() => api.summary(), []);
  if (status !== "success" || !data) return <div className="h-28 border-y border-ink" />;

  if (data.financials_available === false) {
    // District users: the source publishes MPLADS financials per MP and per state, not per district.
    return (
      <section aria-label="Figures for your scope" className="grid border-y border-ink sm:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)]">
        <Flagged data={data} className="pr-6" />
        <p className="border-l border-hairline px-6 py-4 text-sm text-ink-soft">
          Allocation and spend are published per MP and per state, not per district, so they are not shown for {data.scope_label}.
        </p>
      </section>
    );
  }
  return (
    <section aria-label="National figures" className="grid border-y border-ink md:grid-cols-4 lg:grid-cols-[repeat(4,minmax(0,1fr))_minmax(0,1.5fr)]">
      <Figure className="pr-5" label="Allocated" value={formatINR(data.allocated_amount)} note={`${n(data.mps)} MPs`} />
      <Figure className="border-l border-hairline px-5" label="Recommended" value={formatINR(data.recommended_amount)} note={`${n(data.recommended_works)} works`} />
      <Figure className="border-l border-hairline px-5" label="Spent" value={formatINR(data.total_expenditure)} note={`${pct(data.spend_pct_of_allocation)} of allocation`} />
      <Figure className="border-l border-hairline px-5" label="Completion rate" value={pct(data.completion_rate_pct)} note={`${n(data.completed_works)} completed`} />
      <Flagged data={data} className="border-l border-ink pl-6 md:col-span-4 lg:col-span-1" />
    </section>
  );
}
