import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../hooks/useAsync";
import Filters from "../components/Filters";
import Meta from "../components/Meta";
import NationalHeader from "../components/NationalHeader";
import { ScoreBar } from "../components/Severity";
import { Empty, ErrorBox, Loading } from "../components/StateMessage";
import { CASE_STATUS, formatINR, text, titleCase } from "../lib/format";

const PAGE_SIZE = 50;
const DEFAULT = {
  min_score: undefined, derived_category: undefined, state: undefined,
  status: undefined, case_status: undefined, offset: 0,
};

// fixed layout: the project column takes what the rest leave, so the table never scrolls sideways
const COLUMNS = [
  { key: "risk", label: "Risk", sortable: true, w: "w-[76px]" },
  { key: "project", label: "Project" },
  { key: "mp", label: "MP and constituency", w: "w-[188px]" },
  { key: "district", label: "District", w: "w-[132px]" },
  { key: "category", label: "Category", w: "w-[112px]" },
  { key: "case", label: "Case", w: "w-[104px]" },
  { key: "amount", label: "Amount", sortable: true, align: "right", w: "w-[104px]" },
];

export default function RiskListPage({ role, scopeLabel }) {
  const isMp = role === "mp_self";
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  // deep link from the state map: /?state=Karnataka
  const [filters, setFilters] = useState(() => ({ ...DEFAULT, state: searchParams.get("state") || undefined }));
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
    setSort((s) => (s.by === key ? { by: key, order: s.order === "desc" ? "asc" : "desc" } : { by: key, order: "desc" }));
  };

  const page = data ? Math.floor(data.offset / PAGE_SIZE) + 1 : 1;
  const pageCount = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;
  const [exporting, setExporting] = useState(false);
  const exportCsv = async () => {
    setExporting(true);
    try {
      await api.downloadCsv({ ...params, limit: undefined, offset: undefined, sort_by: undefined, order: undefined });
    } catch (e) {
      window.alert(e.message);
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="space-y-8">
      <NationalHeader />

      <section>
        <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
          <div>
            <h2 className="text-xl font-semibold">{isMp ? "Flagged in your portfolio" : "Ranked risk list"}</h2>
            <p className="mt-1 max-w-[62ch] text-ink-soft">
              {isMp
                ? `Everything flagged across your recommended and completed works (${scopeLabel}). Flags are prompts for review, not findings.`
                : "Works ordered by combined risk score, from the rule engine and the anomaly model."}
            </p>
          </div>
          <div className="flex items-center gap-4">
            {data && <span className="text-sm text-ink-soft"><span className="fig text-ink">{data.total.toLocaleString("en-IN")}</span> works</span>}
            <button onClick={() => { setFilters(DEFAULT); setRawQuery(""); }} className="btn">Reset filters</button>
            <button onClick={exportCsv} disabled={exporting} className="btn">
              {exporting ? "Exporting" : "Export CSV"}
            </button>
          </div>
        </div>

        {/* one filter row, ruled off from the table: search and case status first, then the shared filters */}
        <div className="mt-5 border-t border-hairline pt-4">
          <Filters
            value={filters}
            options={options.data}
            onChange={setFilters}
            lead={
              <>
                <label className="flex flex-col gap-1">
                  <span className="label">Search MP, work or work ID</span>
                  <input
                    value={rawQuery}
                    onChange={(e) => setRawQuery(e.target.value)}
                    placeholder="MP name, street light, 178989"
                    className="field w-64"
                  />
                </label>
                <label className="flex flex-col gap-1">
                  <span className="label">Case status</span>
                  <select
                    value={filters.case_status ?? ""}
                    onChange={(e) => setFilters((f) => ({ ...f, case_status: e.target.value || undefined, offset: 0 }))}
                    className="field w-36"
                  >
                    <option value="">All</option>
                    <option value="pending">Pending</option>
                    <option value="under_review">Under review</option>
                    <option value="confirmed">Confirmed</option>
                    <option value="dismissed">Dismissed</option>
                  </select>
                </label>
              </>
            }
          />
        </div>

        <div className="mt-6">
          {status === "loading" && <Loading label="Scoring works" />}
          {status === "error" && <ErrorBox error={error} onRetry={reload} />}
          {status === "success" && data.items.length === 0 && (
            <Empty>No works match these filters. Widen the search or lower the minimum score.</Empty>
          )}

          {status === "success" && data.items.length > 0 && (
            <>
              <div className="overflow-x-auto border border-hairline bg-surface">
                <table className="w-full table-fixed text-sm">
                  <thead>
                    <tr className="border-b border-ink text-left text-xs font-medium text-ink-soft">
                      {COLUMNS.map((c) => (
                        <th
                          key={c.key}
                          scope="col"
                          className={`px-3 py-2.5 ${c.w ?? ""} ${c.align === "right" ? "text-right" : ""} ${c.sortable ? "cursor-pointer select-none hover:text-ink" : ""}`}
                          onClick={() => c.sortable && toggleSort(c.key)}
                          aria-sort={c.sortable && sort.by === c.key ? (sort.order === "desc" ? "descending" : "ascending") : undefined}
                        >
                          {c.label}
                          {c.sortable && sort.by === c.key && <span className="ml-1 text-ink">{sort.order === "desc" ? "▾" : "▴"}</span>}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.items.map((p) => (
                      <tr
                        key={p.id}
                        onClick={() => navigate(`/projects/${p.id}`)}
                        className="cursor-pointer border-b border-hairline last:border-b-0 hover:bg-canvas"
                      >
                        <td className="px-3 py-3 align-top"><ScoreBar score={p.combined_risk_score} /></td>
                        <td className="px-3 py-3 align-top">
                          <p className="truncate font-medium" title={text(p.work_description, "")}>
                            {text(p.work_description, "Untitled work")}
                          </p>
                          <p className="mt-0.5 text-xs text-ink-soft">
                            <Meta items={[<span className="fig">{text(p.external_id, "no id")}</span>, titleCase(p.status)]} />
                          </p>
                          {p.top_reasons?.length > 0 && (
                            <p className="mt-1 truncate text-xs text-ink-soft" title={p.top_reasons.join(" / ")}>
                              {p.top_reasons.join("  ")}
                            </p>
                          )}
                        </td>
                        <td className="px-3 py-3 align-top">
                          <p>{text(p.mp_name)}</p>
                          <p className="text-xs text-ink-soft">{text(p.constituency)}</p>
                        </td>
                        <td className="px-3 py-3 align-top">
                          <p>{text(p.district)}</p>
                          <p className="text-xs text-ink-soft">
                            {p.work_state ? p.work_state : p.district ? "location unresolved" : "no location recorded"}
                          </p>
                        </td>
                        <td className="px-3 py-3 align-top text-ink-soft">{titleCase(p.derived_category) || "-"}</td>
                        <td className="px-3 py-3 align-top">
                          {p.case_status !== "pending" && (
                            <span className={`inline-block px-2 py-0.5 text-xs font-medium ${CASE_STATUS[p.case_status]?.chip || ""}`}>
                              {CASE_STATUS[p.case_status]?.label || p.case_status}
                            </span>
                          )}
                        </td>
                        <td className="fig px-3 py-3 text-right align-top">{formatINR(p.amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="mt-4 flex items-center justify-between">
                <span className="text-sm text-ink-soft">
                  Page <span className="fig text-ink">{page}</span> of <span className="fig text-ink">{pageCount.toLocaleString("en-IN")}</span>
                </span>
                <div className="flex gap-2">
                  <button disabled={filters.offset === 0} onClick={() => setFilters((f) => ({ ...f, offset: Math.max(0, f.offset - PAGE_SIZE) }))} className="btn">
                    Previous
                  </button>
                  <button disabled={page >= pageCount} onClick={() => setFilters((f) => ({ ...f, offset: f.offset + PAGE_SIZE }))} className="btn">
                    Next
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </section>
    </div>
  );
}
