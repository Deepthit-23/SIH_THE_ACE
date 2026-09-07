import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../hooks/useAsync";
import Filters from "../components/Filters";
import NationalHeader from "../components/NationalHeader";
import { ScoreBar } from "../components/Severity";
import { Empty, ErrorBox, Loading } from "../components/StateMessage";
import { CASE_STATUS, formatINR, text, titleCase } from "../lib/format";

const PAGE_SIZE = 50;
const DEFAULT = {
  min_score: undefined, derived_category: undefined, state: undefined,
  status: undefined, case_status: undefined, offset: 0,
};

const COLUMNS = [
  { key: "risk", label: "Risk", sortable: true },
  { key: "project", label: "Project", sortable: false },
  { key: "mp", label: "MP / Constituency", sortable: false },
  { key: "district", label: "District", sortable: false },
  { key: "category", label: "Category", sortable: false },
  { key: "case", label: "Case", sortable: false },
  { key: "amount", label: "Amount", sortable: true, align: "right" },
];

export default function RiskListPage() {
  const navigate = useNavigate();
  const [filters, setFilters] = useState(DEFAULT);
  const [sort, setSort] = useState({ by: "risk", order: "desc" });
  const [rawQuery, setRawQuery] = useState("");
  const [query, setQuery] = useState("");

  useEffect(() => {
    const t = setTimeout(() => {
      setQuery(rawQuery.trim());
      setFilters((f) => ({ ...f, offset: 0 }));
    }, 300);
    return () => clearTimeout(t);
  }, [rawQuery]);

  const options = useAsync(() => api.filters(), []);

  const params = useMemo(
    () => ({
      limit: PAGE_SIZE,
      offset: filters.offset,
      sort_by: sort.by,
      order: sort.order,
      min_score: filters.min_score,
      derived_category: filters.derived_category,
      state: filters.state,
      status: filters.status,
      case_status: filters.case_status,
      q: query || undefined,
    }),
    [filters, sort, query],
  );

  const { status, data, error, reload } = useAsync(() => api.riskScores(params), [params]);

  const toggleSort = (key) => {
    if (!["risk", "amount"].includes(key)) return;
    setSort((s) =>
      s.by === key ? { by: key, order: s.order === "desc" ? "asc" : "desc" } : { by: key, order: "desc" },
    );
  };

  const page = data ? Math.floor(data.offset / PAGE_SIZE) + 1 : 1;
  const pageCount = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;
  const csvHref = api.exportCsvUrl({ ...params, limit: undefined, offset: undefined, sort_by: undefined, order: undefined });

  return (
    <div className="space-y-4">
      <NationalHeader />

      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold">Ranked risk list</h2>
          <p className="text-sm text-slate-500">
            Projects ordered by combined risk score (rule engine + anomaly model).
          </p>
        </div>
        <div className="flex items-center gap-3">
          {data && <span className="text-xs text-slate-500">{data.total.toLocaleString()} projects</span>}
          <a
            href={csvHref}
            className="rounded border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
          >
            Export CSV
          </a>
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs text-slate-500">
          Search MP / work / Work ID
          <input
            value={rawQuery}
            onChange={(e) => setRawQuery(e.target.value)}
            placeholder="e.g. RAHUL GANDHI, street light, 178989"
            className="w-72 rounded border border-slate-300 px-2 py-1.5 text-sm focus:border-slate-400 focus:outline-none"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-slate-500">
          Case status
          <select
            value={filters.case_status ?? ""}
            onChange={(e) => setFilters((f) => ({ ...f, case_status: e.target.value || undefined, offset: 0 }))}
            className="rounded border border-slate-300 bg-white px-2 py-1.5 text-sm focus:border-slate-400 focus:outline-none"
          >
            <option value="">All</option>
            <option value="pending">Pending</option>
            <option value="under_review">Under review</option>
            <option value="confirmed">Confirmed</option>
            <option value="dismissed">Dismissed</option>
          </select>
        </label>
      </div>

      <Filters
        value={filters}
        options={options.data}
        onChange={setFilters}
        onReset={() => { setFilters(DEFAULT); setRawQuery(""); }}
      />

      {status === "loading" && <Loading label="Scoring projects…" />}
      {status === "error" && <ErrorBox error={error} onRetry={reload} />}

      {status === "success" && data.items.length === 0 && (
        <Empty>No projects match these filters. Try widening the search or lowering the minimum score.</Empty>
      )}

      {status === "success" && data.items.length > 0 && (
        <>
          <div className="overflow-x-auto rounded border border-slate-200 bg-white">
            <table className="min-w-full text-sm">
              <thead className="border-b border-slate-200 bg-slate-50 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
                <tr>
                  {COLUMNS.map((c) => (
                    <th
                      key={c.key}
                      className={`px-3 py-2 ${c.align === "right" ? "text-right" : ""} ${
                        c.sortable ? "cursor-pointer select-none hover:text-slate-700" : ""
                      }`}
                      onClick={() => c.sortable && toggleSort(c.key)}
                    >
                      {c.label}
                      {c.sortable && sort.by === c.key && (
                        <span className="ml-1">{sort.order === "desc" ? "▾" : "▴"}</span>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.items.map((p) => (
                  <tr
                    key={p.id}
                    onClick={() => navigate(`/projects/${p.id}`)}
                    className="cursor-pointer hover:bg-slate-50"
                  >
                    <td className="px-3 py-2.5">
                      <ScoreBar score={p.combined_risk_score} />
                    </td>
                    <td className="max-w-sm px-3 py-2.5">
                      <p className="truncate font-medium text-slate-800" title={text(p.work_description, "")}>
                        {text(p.work_description, "Untitled work")}
                      </p>
                      <p className="text-xs text-slate-400">
                        {text(p.external_id, "no id")} · {titleCase(p.status)}
                      </p>
                      {p.top_reasons?.length > 0 && (
                        <p className="mt-0.5 truncate text-xs text-slate-500" title={p.top_reasons.join(" · ")}>
                          {p.top_reasons.join("  ·  ")}
                        </p>
                      )}
                    </td>
                    <td className="px-3 py-2.5">
                      <p className="text-slate-700">{text(p.mp_name)}</p>
                      <p className="text-xs text-slate-400">{text(p.constituency)}</p>
                    </td>
                    <td className="px-3 py-2.5 text-slate-600">
                      {text(p.district)}
                      <span className="block text-xs text-slate-400">{text(p.state)}</span>
                    </td>
                    <td className="px-3 py-2.5 text-slate-600">{titleCase(p.derived_category) || "—"}</td>
                    <td className="px-3 py-2.5">
                      {p.case_status !== "pending" && (
                        <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${CASE_STATUS[p.case_status]?.chip || ""}`}>
                          {CASE_STATUS[p.case_status]?.label || p.case_status}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-slate-700">
                      {formatINR(p.amount)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between text-sm">
            <span className="text-slate-500">
              Page {page} of {pageCount.toLocaleString()}
            </span>
            <div className="flex gap-2">
              <button
                disabled={filters.offset === 0}
                onClick={() => setFilters((f) => ({ ...f, offset: Math.max(0, f.offset - PAGE_SIZE) }))}
                className="rounded border border-slate-300 px-3 py-1 text-xs font-medium disabled:opacity-40"
              >
                Previous
              </button>
              <button
                disabled={page >= pageCount}
                onClick={() => setFilters((f) => ({ ...f, offset: f.offset + PAGE_SIZE }))}
                className="rounded border border-slate-300 px-3 py-1 text-xs font-medium disabled:opacity-40"
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
