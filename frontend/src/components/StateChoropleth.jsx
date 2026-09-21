import { useEffect, useMemo, useState } from "react";
import { T } from "../lib/tokens";
import { useNavigate } from "react-router-dom";
import { geoMercator, geoPath } from "d3-geo";
import { api } from "../api/client";
import { useAsync } from "../hooks/useAsync";
import { Empty, ErrorBox, Loading } from "./StateMessage";

// State-level choropleth. Data: GET /patterns/states (already scoped server-side, so a State user only
// receives their own state). Geometry: DataMeet India state boundaries (CC BY 4.0), lazy-loaded; the
// join is on the canonical state name baked into each feature (`properties.state`), exact equality.

const METRICS = {
  flagged_pct: { label: "Flagged share", unit: "%", note: "share of projects scoring ≥ 50", floor: 10 },
  avg_risk_score: { label: "Average risk score", unit: "", note: "mean combined score, 0–100", floor: 20 },
};
const LOW = [247, 239, 238];   // surface tinted toward the high tier
const HIGH = [162, 59, 59];    // T.high
const NO_DATA = T.canvas;

const mix = (t) => `rgb(${LOW.map((l, i) => Math.round(l + (HIGH[i] - l) * t)).join(",")})`;

export function colourFor(value, lo, hi) {
  if (value === null || value === undefined || Number.isNaN(value)) return NO_DATA;
  const t = hi > lo ? (value - lo) / (hi - lo) : 1;
  return mix(Math.max(0, Math.min(1, t)) ** 0.6);   // gentle curve: a few small-count outliers must not wash out the rest
}

const W = 560, H = 620;
/** "The Dadra And Nagar Haveli And Daman And Diu" -> "Dadra & Nagar Haveli & Daman & Diu" (display only). */
export const shortName = (s) => s.replace(/^The /, "").replace(/ And /g, " & ");

function Stat({ label, value, sub }) {
  return (
    <div className="rounded border border-hairline bg-canvas p-3">
      <p className="text-[11px] text-ink-faint">{label}</p>
      <p className="mt-0.5 text-xl font-semibold tabular-nums text-ink">{value}</p>
      {sub && <p className="text-[11px] text-ink-soft">{sub}</p>}
    </div>
  );
}

/** Compact figures for a District / MP scope, headed by the full scope ("HYDERABAD, Telangana"). */
function ScopeSummary({ label, kind, items }) {
  const n = items.reduce((a, i) => a + i.project_count, 0);
  const flagged = items.reduce((a, i) => a + i.flagged_count, 0);
  const high = items.reduce((a, i) => a + i.high_risk_count, 0);
  const avg = n ? items.reduce((a, i) => a + i.avg_risk_score * i.project_count, 0) / n : 0;
  const what = kind === "district" ? "this district" : "your portfolio";
  return (
    <div className="rounded border border-hairline bg-surface p-4" data-testid="scope-summary">
      <h3 className="text-sm font-semibold text-ink">{label}</h3>
      <p className="text-xs text-ink-soft">
        Figures count only the projects in {what}. A map of the whole state would misstate a narrower scope.
      </p>
      <div className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Projects" value={n.toLocaleString()} />
        <Stat label="Flagged (score ≥ 50)" value={flagged.toLocaleString()} sub={`${n ? ((100 * flagged) / n).toFixed(1) : 0}% of projects`} />
        <Stat label="Average risk score" value={avg.toFixed(1)} sub="0–100" />
        <Stat label="High risk (score ≥ 70)" value={high.toLocaleString()} sub={`${n ? ((100 * high) / n).toFixed(1) : 0}% of projects`} />
      </div>
    </div>
  );
}

export default function StateChoropleth() {
  const navigate = useNavigate();
  const agg = useAsync(() => api.stateAggregates(), []);
  const [geo, setGeo] = useState(null);
  const [metric, setMetric] = useState("flagged_pct");
  const [hover, setHover] = useState(null);

  // A whole-state colour is only accurate when the scope IS the state (or the nation). District and MP scopes
  // are a slice of a state, so they get a summary card instead of a map (and never download the geometry).
  const kind = agg.data?.scope_kind;
  const drawsMap = kind === "national" || kind === "state";

  useEffect(() => {
    if (!drawsMap) return undefined;
    let alive = true;
    import("../assets/india-states.json").then((m) => alive && setGeo(m.default));
    return () => { alive = false; };
  }, [drawsMap]);

  const items = agg.data?.items ?? [];
  const byState = useMemo(() => new Map(items.map((i) => [i.state, i])), [items]);
  const national = agg.data?.scope_label === "National";

  const view = useMemo(() => {
    if (!geo || !items.length) return null;
    // outside the national view, draw only the states the user actually has data for
    const feats = geo.features.filter((f) => national || byState.has(f.properties.state));
    const fc = { type: "FeatureCollection", features: feats };
    const proj = geoMercator().fitExtent([[8, 8], [W - 8, H - 8]], fc);
    const path = geoPath(proj);
    const values = items.map((i) => i[metric]);
    // Scale is anchored at 0 and its top is never below `floor`, so a lone in-scope state that is only
    // mildly risky reads as pale, not as "maximum" merely because it is the only value.
    return { feats, path, lo: 0, hi: Math.max(METRICS[metric].floor, ...values) };
  }, [geo, items, byState, national, metric]);

  const unmatched = useMemo(() => {
    if (!geo) return [];
    const names = new Set(geo.features.map((f) => f.properties.state));
    return items.filter((i) => !names.has(i.state)).map((i) => i.state);
  }, [geo, items]);

  const ranked = useMemo(() => [...items].sort((a, b) => b[metric] - a[metric]), [items, metric]);
  const focus = hover ? byState.get(hover) : null;
  const fmt = (i, m) => (m === "flagged_pct" ? `${i.flagged_pct}%` : i.avg_risk_score.toFixed(1));

  if (agg.status === "success" && items.length > 0 && !drawsMap) {
    return <ScopeSummary label={agg.data.scope_label} kind={kind} items={items} />;
  }

  return (
    <div className="rounded border border-hairline bg-surface p-4" data-testid="state-choropleth">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-ink">Risk by state</h3>
          <p className="text-xs text-ink-soft">
            {national ? "All states and UTs." : `Only your scope: ${agg.data?.scope_label ?? ""}. Figures count just the projects in that scope.`}{" "}
            Colour = {METRICS[metric].note}.
          </p>
        </div>
        <div className="flex overflow-hidden rounded border border-hairline text-xs" role="group" aria-label="Colour by">
          {Object.entries(METRICS).map(([k, m]) => (
            <button key={k} onClick={() => setMetric(k)}
              className={`px-3 py-1.5 ${metric === k ? "bg-ink text-surface" : "bg-surface text-ink-soft hover:bg-canvas"}`}>
              {m.label}
            </button>
          ))}
        </div>
      </div>

      {agg.status === "loading" && <Loading label="Loading state figures…" />}
      {agg.status === "error" && <ErrorBox error={agg.error} onRetry={agg.reload} />}
      {agg.status === "success" && items.length === 0 && <Empty>No scored projects in your scope.</Empty>}

      {agg.status === "success" && items.length > 0 && (
        <div className="mt-3 grid gap-4 lg:grid-cols-[minmax(0,1fr)_16rem]">
          <div>
            {!view ? (
              <Loading label="Loading map…" />
            ) : (
              <svg viewBox={`0 0 ${W} ${H}`} className="mx-auto h-auto w-full max-w-[34rem]" role="img"
                aria-label={`India state map coloured by ${METRICS[metric].label}`}>
                {view.feats.map((f) => {
                  const name = f.properties.state;
                  const row = byState.get(name);
                  const active = hover === name;
                  return (
                    <path
                      key={name}
                      d={view.path(f)}
                      fill={colourFor(row?.[metric], view.lo, view.hi)}
                      stroke={active ? T.ink : T.surface}
                      strokeWidth={active ? 1.4 : 0.6}
                      onMouseEnter={() => setHover(name)}
                      onMouseLeave={() => setHover(null)}
                      onClick={() => row && navigate(`/?state=${encodeURIComponent(name)}`)}
                      style={{ cursor: row ? "pointer" : "default" }}
                    >
                      <title>{row ? `${name}: ${fmt(row, metric)} (${row.flagged_count.toLocaleString()} of ${row.project_count.toLocaleString()} flagged)` : `${name}: outside your scope`}</title>
                    </path>
                  );
                })}
              </svg>
            )}
            <div className="mx-auto mt-2 flex max-w-[34rem] items-center gap-2 text-[11px] text-ink-soft">
              <span className="tabular-nums">{view ? `${view.lo.toFixed(metric === "flagged_pct" ? 0 : 1)}${METRICS[metric].unit}` : ""}</span>
              <span className="h-2 flex-1 rounded" style={{ background: `linear-gradient(to right, ${mix(0)}, ${mix(0.5)}, ${mix(1)})` }} />
              <span className="tabular-nums">{view ? `${view.hi.toFixed(metric === "flagged_pct" ? 0 : 1)}${METRICS[metric].unit}` : ""}</span>
            </div>
          </div>

          <div className="min-w-0">
            <div className="mb-2 min-h-[4.5rem] rounded border border-hairline bg-canvas p-2 text-xs">
              {focus ? (
                <>
                  <p className="font-semibold text-ink">{shortName(focus.state)}</p>
                  <p className="text-ink-soft">{focus.project_count.toLocaleString()} projects, {focus.flagged_count.toLocaleString()} flagged ({focus.flagged_pct}%)</p>
                  <p className="text-ink-soft">average score {focus.avg_risk_score}, {focus.high_risk_count.toLocaleString()} high risk</p>
                </>
              ) : (
                <p className="text-ink-faint">Hover a state or a row. Click to open its projects.</p>
              )}
            </div>
            <ol className="max-h-[27rem] space-y-0.5 overflow-y-auto pr-1">
              {ranked.map((r) => (
                <li key={r.state}>
                  <button
                    onMouseEnter={() => setHover(r.state)} onMouseLeave={() => setHover(null)}
                    onClick={() => navigate(`/?state=${encodeURIComponent(r.state)}`)}
                    className={`grid w-full grid-cols-[minmax(0,1fr)_3rem] items-center gap-2 rounded px-1.5 py-0.5 text-left text-xs ${hover === r.state ? "bg-canvas" : ""}`}
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-ink" title={r.state}>{shortName(r.state)}</span>
                      <span className="mt-0.5 block h-1 rounded bg-canvas">
                        <span className="block h-full rounded" style={{
                          width: `${view ? Math.max(3, ((r[metric] - 0) / (view.hi || 1)) * 100) : 0}%`,
                          background: colourFor(r[metric], view?.lo ?? 0, view?.hi ?? 1) }} />
                      </span>
                    </span>
                    <span className="text-right tabular-nums text-ink-soft">{fmt(r, metric)}</span>
                  </button>
                </li>
              ))}
            </ol>
          </div>
        </div>
      )}

      {(agg.data?.unlocated_count ?? 0) > 0 && (
        <p className="mt-2 text-xs text-ink-soft">
          {agg.data.unlocated_count.toLocaleString()} project{agg.data.unlocated_count === 1 ? "" : "s"} could not be placed on a
          state (no district recorded, or an ambiguous district name). They count in national totals but not on this map or in any state view.
        </p>
      )}
      {unmatched.length > 0 && (
        <p className="mt-2 text-xs text-ink">Not drawn (no matching map shape): {unmatched.join(", ")}.</p>
      )}
      <p className="mt-3 text-[10px] text-ink-faint">
        India state boundaries by DataMeet India community (CC BY 4.0), simplified for display. Illustrative;
        not an authoritative depiction of international boundaries.
      </p>
    </div>
  );
}
