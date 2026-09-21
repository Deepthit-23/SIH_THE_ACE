import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { T } from "../lib/tokens";
import { Bar, BarChart, CartesianGrid, Tooltip, XAxis, YAxis } from "recharts";

/** Track a container's width with ResizeObserver -- avoids Recharts'
 *  ResponsiveContainer, which collapses when the page layout shifts. */
function useElementWidth() {
  const ref = useRef(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      const w = entry.contentRect.width;
      if (w) setWidth(Math.floor(w));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}
import { api } from "../api/client";
import { useAsync } from "../hooks/useAsync";
import { SeverityBadge } from "../components/Severity";
import StateChoropleth from "../components/StateChoropleth";
import { Empty, ErrorBox, Loading } from "../components/StateMessage";
import { formatINR, severityFor, SEVERITY, text, titleCase } from "../lib/format";

const ChartCard = memo(function ChartCard({ title, subtitle, rows, dataKey, tooltipLabel, onSelect }) {
  const [wrapRef, width] = useElementWidth();
  if (!rows || rows.length === 0) return <Empty>No data.</Empty>;
  const height = Math.max(240, rows.length * 32);
  return (
    <div className="rounded border border-hairline bg-surface p-4">
      <h3 className="text-sm font-semibold text-ink">{title}</h3>
      <p className="mb-3 text-xs text-ink-soft">{subtitle}</p>
      <div ref={wrapRef} className="w-full">
        {width > 0 && (
          <BarChart
            width={width}
            height={height}
            data={rows}
            layout="vertical"
            margin={{ left: 8, right: 24, top: 4, bottom: 4 }}
          >
            <CartesianGrid horizontal={false} stroke={T.hairline} />
            <XAxis type="number" tick={{ fontSize: 11, fill: T.inkFaint }} />
            <YAxis
              type="category"
              dataKey={rows[0]?.label ? "label" : "key"}
              interval={0}
              width={170}
              tick={{ fontSize: 11, fill: T.inkSoft }}
              tickFormatter={(v) => (v.length > 26 ? v.slice(0, 25) + "…" : v)}
            />
            <Tooltip
              cursor={{ fill: T.canvas }}
              formatter={(v) => [v, tooltipLabel]}
              labelStyle={{ fontSize: 12 }}
              contentStyle={{ fontSize: 12, borderRadius: 6 }}
            />
            <Bar
              dataKey={dataKey}
              radius={[0, 3, 3, 0]}
              isAnimationActive={false}
              fill={T.ink}
              cursor="pointer"
              onClick={(d) => {
                const row = d?.payload ?? d;
                if (row?.key) onSelect(row.key, row);
              }}
            />
          </BarChart>
        )}
      </div>
      <p className="mt-1 text-xs text-ink-faint">Click a bar for detail.</p>
    </div>
  );
});

function DistrictDetail({ name, state }) {
  const { status, data, error } = useAsync(() => api.districtPattern(name, { threshold: 70, state }), [name, state]);
  if (status === "loading") return <Loading />;
  if (status === "error") return <ErrorBox error={error} />;

  const maxCat = Math.max(...data.categories.map((c) => c.project_count), 1);
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <h4 className="text-sm font-semibold">{data.district}{data.state ? `, ${data.state}` : ""}</h4>
        <SeverityBadge score={data.avg_risk_score} />
      </div>
      <div className="grid grid-cols-3 gap-3 text-center">
        <Stat label="Projects" value={data.project_count.toLocaleString()} />
        <Stat label="Avg risk" value={data.avg_risk_score} />
        <Stat label="High risk (≥70)" value={data.high_risk_count.toLocaleString()} />
      </div>
      <div>
        <p className="mb-1 text-xs font-medium text-ink-faint">
          By category
        </p>
        <ul className="space-y-1">
          {data.categories.map((c) => (
            <li key={c.derived_category} className="text-xs">
              <div className="flex justify-between text-ink-soft">
                <span>{titleCase(c.derived_category)}</span>
                <span className="tabular-nums">
                  {c.project_count}, average {c.avg_risk_score}
                </span>
              </div>
              <div className="mt-0.5 h-1.5 w-full rounded bg-canvas">
                <div
                  className="h-full rounded"
                  style={{
                    width: `${(c.project_count / maxCat) * 100}%`,
                    backgroundColor: SEVERITY[severityFor(c.avg_risk_score)].fill,
                  }}
                />
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function ContractorDetail({ name }) {
  const { status, data, error } = useAsync(() => api.contractorPattern(name), [name]);
  if (status === "loading") return <Loading />;
  if (status === "error") return <ErrorBox error={error} />;

  return (
    <div className="space-y-3">
      <h4 className="text-sm font-semibold">{text(data.vendor)}</h4>
      <div className="grid grid-cols-2 gap-3 text-center">
        <Stat label="Transactions" value={data.total_txn_count.toLocaleString()} />
        <Stat label="Total value" value={formatINR(data.total_txn_value)} />
        <Stat label="In over-concentrated units" value={data.flagged_txn_count.toLocaleString()} />
        <Stat label="Peak share of an MP" value={`${Math.round(data.max_share_of_unit_value * 100)}%`} />
      </div>
      <div>
        <p className="mb-1 text-xs font-medium text-ink-faint">
          Concentration by MP / constituency
        </p>
        <div className="overflow-x-auto">
          <table className="min-w-full text-xs">
            <thead className="text-left text-ink-faint">
              <tr>
                <th className="py-1 pr-2">MP</th>
                <th className="py-1 pr-2">Constituency</th>
                <th className="py-1 pr-2 text-right">Txns</th>
                <th className="py-1 pr-2 text-right">Value share</th>
                <th className="py-1"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-hairline">
              {data.units.slice(0, 8).map((u, i) => (
                <tr key={i} className="text-ink-soft">
                  <td className="py-1 pr-2">{text(u.mp_name)}</td>
                  <td className="py-1 pr-2">{text(u.constituency)}</td>
                  <td className="py-1 pr-2 text-right tabular-nums">{u.txn_count}</td>
                  <td className="py-1 pr-2 text-right tabular-nums">
                    {Math.round(u.share_of_unit_value * 100)}%
                  </td>
                  <td className="py-1">
                    {u.concentration_flagged && (
                      <span className="px-1.5 py-0.5 text-[10px] font-medium border-l-[3px] border-high bg-high/10 text-ink">
                        concentrated
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div className="rounded border border-hairline bg-canvas p-2">
      <p className="text-sm font-semibold text-ink">{value}</p>
      <p className="text-[11px] text-ink-soft">{label}</p>
    </div>
  );
}

export default function PatternsPage() {
  const districts = useAsync(() => api.rankDistricts({ limit: 15, threshold: 70 }), []);
  const contractors = useAsync(() => api.rankContractors({ limit: 15 }), []);
  const [selected, setSelected] = useState(null); // { dim, key }

  const selectDistrict = useCallback((key, row) => setSelected({ dim: "district", key, state: row?.state }), []);
  const selectContractor = useCallback((key) => setSelected({ dim: "contractor", key }), []);

  // district names repeat across states: label every bar with its state and carry the state into the drill-down
  const districtRows = useMemo(
    () => (districts.data?.items ?? []).filter((d) => d.key !== "(unknown)")
      .map((d) => ({ ...d, label: d.state ? `${d.key}, ${d.state}` : d.key })),
    [districts.data],
  );
  const contractorRows = useMemo(
    () => contractors.data?.items ?? [],
    [contractors.data],
  );

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">District &amp; contractor patterns</h2>
        <p className="text-sm text-ink-soft">
          Where risk concentrates — for spotting systemic issues, not one-off flags.
        </p>
      </div>

      <StateChoropleth />

      <div className="grid gap-4 lg:grid-cols-2">
        {districts.status === "loading" && <Loading />}
        {districts.status === "error" && <ErrorBox error={districts.error} onRetry={districts.reload} />}
        {districts.status === "success" && (
          <ChartCard
            title="Districts by high-risk project count"
            subtitle="Projects scoring ≥ 70, by district (top 15)"
            rows={districtRows}
            dataKey="high_risk_count"
            tooltipLabel="high-risk projects"
            onSelect={selectDistrict}
          />
        )}

        {contractors.status === "loading" && <Loading />}
        {contractors.status === "error" && (
          <ErrorBox error={contractors.error} onRetry={contractors.reload} />
        )}
        {contractors.status === "success" &&
          (contractors.data.items.length === 0 ? (
            <Empty>No over-concentrated contractors found.</Empty>
          ) : (
            <ChartCard
              title="Contractors by concentrated transaction count"
              subtitle="Transactions in MP units where the vendor is over-concentrated (top 15)"
              rows={contractorRows}
              dataKey="flagged_txn_count"
              tooltipLabel="concentrated transactions"
              onSelect={selectContractor}
            />
          ))}
      </div>

      {selected && (
        <div className="rounded border border-hairline bg-surface p-4">
          <div className="mb-3 flex items-center justify-between">
            <span className="text-xs font-medium text-ink-faint">
              {selected.dim === "district" ? "District detail" : "Contractor detail"}
            </span>
            <button
              onClick={() => setSelected(null)}
              className="text-xs text-ink-faint hover:text-ink-soft"
            >
              Close ✕
            </button>
          </div>
          {selected.dim === "district" ? (
            <DistrictDetail name={selected.key} state={selected.state} />
          ) : (
            <ContractorDetail name={selected.key} />
          )}
        </div>
      )}
    </div>
  );
}
