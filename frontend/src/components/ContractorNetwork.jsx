// NOT CURRENTLY MOUNTED: hidden from the Patterns page at the owner's request. Kept (with api.contractorNetwork and the
// backend GET /patterns/network) so it can be restored by re-adding `<ContractorNetwork />` to PatternsPage.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { T } from "../lib/tokens";
import ForceGraph2D from "react-force-graph-2d";
import { forceX, forceY } from "d3-force";
import { api } from "../api/client";
import { useAsync } from "../hooks/useAsync";
import { formatINR } from "../lib/format";
import { Empty, ErrorBox, Loading } from "./StateMessage";

// Contractor <-> MP network. Data: GET /patterns/network -- only the strongest FLAGGED concentration
// relationships (the contractor rule's own thresholds), already scoped server-side. Edge width = the
// vendor's transaction value with that MP; a vendor node's size = its total value across the shown edges.

const COL = { mp: T.ink, vendor: T.high, edge: T.inkFaint, edgeHot: T.ink, dim: T.hairline };
const LIMITS = [20, 40, 80, 150];
const trunc = (s, n) => (s.length > n ? s.slice(0, n - 1) + "…" : s);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const clean = (s) => String(s || "").replace(/\s*\(\d{4}-\d{2,4}\)\s*$/, "").replace(/^(Shri|Smt\.?|Dr\.?|Prof\.?)\s+/i, "");

/** Turn API edges into force-graph nodes/links. Exported for testing. */
export function buildGraph(edges) {
  const nodes = new Map();
  const links = [];
  for (const e of edges) {
    const mpId = `mp:${e.mp_name}|${e.constituency ?? ""}`;
    const vId = `v:${e.vendor}`;
    if (!nodes.has(mpId)) nodes.set(mpId, { id: mpId, kind: "mp", label: clean(e.mp_name), place: e.constituency, state: e.state, value: 0, maxShare: 0 });
    if (!nodes.has(vId)) nodes.set(vId, { id: vId, kind: "vendor", label: e.vendor, value: 0, maxShare: 0 });
    for (const id of [mpId, vId]) {
      const n = nodes.get(id);
      n.value += e.txn_value;
      n.maxShare = Math.max(n.maxShare, e.share_of_unit_value);
    }
    links.push({ source: mpId, target: vId, ...e });
  }
  return { nodes: [...nodes.values()], links };
}

/** Width of an element that may mount late (it only renders once data has arrived): callback ref. */
function useWidth() {
  const [el, setEl] = useState(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    if (!el) return undefined;
    setW(Math.floor(el.getBoundingClientRect().width));
    const ro = new ResizeObserver(([e]) => setW(Math.floor(e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, [el]);
  return [setEl, w];
}

export default function ContractorNetwork() {
  const [limit, setLimit] = useState(40);
  const { status, data, error, reload } = useAsync(() => api.contractorNetwork({ limit }), [limit]);
  const [wrapRef, width] = useWidth();
  const fg = useRef(null);
  const [hover, setHover] = useState(null);      // node id
  const [picked, setPicked] = useState(null);    // node id

  const graph = useMemo(() => buildGraph(data?.edges ?? []), [data]);
  const maxLink = useMemo(() => Math.max(1, ...graph.links.map((l) => l.txn_value)), [graph]);
  const maxNode = useMemo(() => Math.max(1, ...graph.nodes.filter((n) => n.kind === "vendor").map((n) => n.value)), [graph]);
  const nodeById = useMemo(() => new Map(graph.nodes.map((n) => [n.id, n])), [graph]);
  const neighbours = useMemo(() => {
    const m = new Map(graph.nodes.map((n) => [n.id, new Set([n.id])]));
    graph.links.forEach((l) => {
      const s = l.source.id ?? l.source, t = l.target.id ?? l.target;
      m.get(s)?.add(t); m.get(t)?.add(s);
    });
    return m;
  }, [graph]);

  // weak centring forces keep the (mostly disconnected) pairs and stars close enough to read together
  useEffect(() => {
    const g = fg.current;
    if (!g) return;
    g.d3Force("x", forceX(0).strength(0.06));
    g.d3Force("y", forceY(0).strength(0.06));
    g.d3Force("charge")?.strength(-70);
    g.d3Force("link")?.distance(38);
  }, [graph, width]);

  const focusId = hover ?? picked;
  const lit = focusId ? neighbours.get(focusId) : null;
  const radius = (n) => (n.kind === "vendor" ? 3.5 + 7 * Math.sqrt(n.value / maxNode) : 4);

  const drawNode = useCallback((n, ctx, scale) => {
    const faded = lit && !lit.has(n.id);
    const r = radius(n);
    ctx.globalAlpha = faded ? 0.18 : 1;
    ctx.fillStyle = n.kind === "mp" ? COL.mp : COL.vendor;
    ctx.beginPath();
    if (n.kind === "mp") ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
    else ctx.rect(n.x - r, n.y - r, 2 * r, 2 * r);
    ctx.fill();
    if (n.id === focusId) { ctx.lineWidth = 1.5 / scale; ctx.strokeStyle = T.ink; ctx.stroke(); }
    // labels: on hover/selection and for the biggest vendors once zoomed a bit
    if (!faded && (n.id === focusId || (lit && lit.has(n.id)) || (scale > 1.6 && n.kind === "vendor" && n.value > maxNode * 0.4))) {
      ctx.font = `${10 / scale}px Inter, system-ui, sans-serif`;
      ctx.fillStyle = T.ink;
      ctx.textAlign = "center";
      // contractor labels above, MP labels below, so a linked pair never prints over itself
      ctx.fillText(trunc(n.label, 26), n.x, n.kind === "vendor" ? n.y - r - 4 / scale : n.y + r + 9 / scale);
    }
    ctx.globalAlpha = 1;
  }, [lit, focusId, maxNode]);   // eslint-disable-line react-hooks/exhaustive-deps

  const sel = picked ? nodeById.get(picked) : null;
  const selLinks = sel ? graph.links.filter((l) => (l.source.id ?? l.source) === sel.id || (l.target.id ?? l.target) === sel.id) : [];

  return (
    <div className="rounded border border-hairline bg-surface p-4" data-testid="contractor-network">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-ink">Contractor–MP network</h3>
          <p className="text-xs text-ink-soft">
            Only relationships the concentration rule flags: a vendor holding ≥ {Math.round((data?.share_threshold ?? 0.6) * 100)}% of an MP’s
            transactions. Line width = transaction value. {data && data.scope_label !== "National" ? `Scope: ${data.scope_label}.` : ""}
          </p>
        </div>
        <label className="flex items-center gap-2 text-xs text-ink-soft">
          Show top
          <select value={limit} onChange={(e) => { setLimit(Number(e.target.value)); setPicked(null); }}
            className="rounded border border-hairline bg-surface px-2 py-1.5 text-sm">
            {LIMITS.map((n) => <option key={n} value={n}>{n} relationships</option>)}
          </select>
        </label>
      </div>

      {status === "loading" && <Loading label="Loading relationships…" />}
      {status === "error" && <ErrorBox error={error} onRetry={reload} />}
      {status === "success" && graph.links.length === 0 && (
        <Empty>No over-concentrated contractor relationships in your scope.</Empty>
      )}

      {status === "success" && graph.links.length > 0 && (
        <div className="mt-3 grid gap-4 lg:grid-cols-[minmax(0,1fr)_17rem]">
          <div ref={wrapRef} className="relative overflow-hidden rounded border border-hairline bg-canvas/50">
            {width > 0 && (
              <ForceGraph2D
                ref={fg}
                graphData={graph}
                width={width}
                height={440}
                backgroundColor="rgba(0,0,0,0)"
                nodeCanvasObject={drawNode}
                nodePointerAreaPaint={(n, color, ctx) => { ctx.fillStyle = color; ctx.beginPath(); ctx.arc(n.x, n.y, radius(n) + 3, 0, 2 * Math.PI); ctx.fill(); }}
                linkWidth={(l) => 0.8 + 5 * Math.sqrt(l.txn_value / maxLink)}
                linkColor={(l) => {
                  const s = l.source.id ?? l.source, t = l.target.id ?? l.target;
                  if (!focusId) return COL.edge;
                  return s === focusId || t === focusId ? COL.edgeHot : COL.dim;
                }}
                linkLabel={(l) => `<div style="font:12px system-ui;padding:2px 4px">${esc(clean(l.mp_name))} and ${esc(l.vendor)}<br/>${l.txn_count} txns, ${esc(formatINR(l.txn_value))}, ${Math.round(l.share_of_unit_value * 100)}% of the MP's value</div>`}
                nodeLabel={(n) => `<div style="font:12px system-ui;padding:2px 4px">${esc(n.label)}${n.kind === "mp" ? `<br/>${esc(n.place ?? "")}, ${esc(n.state ?? "")}` : ""}</div>`}
                onNodeHover={(n) => setHover(n ? n.id : null)}
                onNodeClick={(n) => setPicked((p) => (p === n.id ? null : n.id))}
                onBackgroundClick={() => setPicked(null)}
                cooldownTicks={140}
                onEngineStop={() => fg.current?.zoomToFit(300, 36)}
              />
            )}
            <div className="pointer-events-none absolute bottom-2 left-2 flex items-center gap-3 rounded bg-surface/90 px-2 py-1 text-[11px] text-ink-soft">
              <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full" style={{ background: COL.mp }} /> MP</span>
              <span className="flex items-center gap-1"><span className="h-2.5 w-2.5" style={{ background: COL.vendor }} /> Contractor (size = value)</span>
            </div>
          </div>

          <div className="min-w-0 text-xs">
            {!sel ? (
              <div className="rounded border border-hairline bg-canvas p-3 text-ink-soft">
                <p>{graph.links.length} relationships, {graph.nodes.filter((n) => n.kind === "vendor").length} contractors, {graph.nodes.filter((n) => n.kind === "mp").length} MP units.</p>
                <p className="mt-2">Hover a node to isolate its links; click to pin its details here. Drag to rearrange, scroll to zoom.</p>
              </div>
            ) : (
              <div className="rounded border border-hairline bg-surface p-3">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="text-[10px] font-semibold text-ink-faint">{sel.kind === "mp" ? "MP" : "Contractor"}</p>
                    <p className="font-semibold text-ink">{sel.label}</p>
                    {sel.kind === "mp" && <p className="text-ink-soft">{sel.place}, {sel.state}</p>}
                  </div>
                  <button onClick={() => setPicked(null)} className="text-ink-faint hover:text-ink-soft" aria-label="Close">✕</button>
                </div>
                <ul className="mt-2 max-h-72 space-y-1.5 overflow-y-auto">
                  {selLinks.sort((a, b) => b.txn_value - a.txn_value).map((l, i) => (
                    <li key={i} className="rounded bg-canvas p-1.5">
                      <p className="text-ink">{sel.kind === "mp" ? l.vendor : clean(l.mp_name)}</p>
                      <p className="text-ink-soft">{l.txn_count} txns, {formatINR(l.txn_value)}, {Math.round(l.share_of_unit_value * 100)}% of value</p>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
