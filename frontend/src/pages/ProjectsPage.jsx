import { useEffect, useState } from "react";
import { api } from "../api/client";

function formatAmount(value) {
  if (value === null || value === undefined || value === "") return "—";
  const num = Number(value);
  if (Number.isNaN(num)) return "—";
  return num.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

export default function ProjectsPage() {
  const [state, setState] = useState({ status: "loading", data: null, error: null });

  useEffect(() => {
    let cancelled = false;
    api
      .listProjects({ limit: 100 })
      .then((data) => {
        if (!cancelled) setState({ status: "ready", data, error: null });
      })
      .catch((err) => {
        if (!cancelled)
          setState({ status: "error", data: null, error: err.message });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (state.status === "loading") {
    return <p className="text-sm text-slate-500">Loading projects…</p>;
  }

  if (state.status === "error") {
    return (
      <div className="rounded border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Could not load projects: {state.error}
      </div>
    );
  }

  const { total, items } = state.data;

  return (
    <section>
      <div className="mb-4 flex items-baseline justify-between">
        <h2 className="text-base font-semibold">Projects</h2>
        <span className="text-xs text-slate-500">{total} total</span>
      </div>

      {items.length === 0 ? (
        <div className="rounded border border-slate-200 bg-white p-6 text-sm text-slate-500">
          No project data loaded yet. Run the Phase 2 data pipeline to populate the
          database.
        </div>
      ) : (
        <div className="overflow-x-auto rounded border border-slate-200 bg-white">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2">ID</th>
                <th className="px-3 py-2">MP</th>
                <th className="px-3 py-2">State</th>
                <th className="px-3 py-2">District</th>
                <th className="px-3 py-2">Category</th>
                <th className="px-3 py-2 text-right">Sanctioned</th>
                <th className="px-3 py-2 text-right">Spent</th>
                <th className="px-3 py-2">Contractor</th>
                <th className="px-3 py-2">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map((p) => (
                <tr key={p.id} className="hover:bg-slate-50">
                  <td className="px-3 py-2 text-slate-400">{p.id}</td>
                  <td className="px-3 py-2">{p.mp_name || "—"}</td>
                  <td className="px-3 py-2">{p.state || "—"}</td>
                  <td className="px-3 py-2">{p.district || "—"}</td>
                  <td className="px-3 py-2">{p.category || "—"}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {formatAmount(p.sanctioned_amount)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {formatAmount(p.spent_amount)}
                  </td>
                  <td className="px-3 py-2">{p.contractor_name || "—"}</td>
                  <td className="px-3 py-2">{p.status || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
