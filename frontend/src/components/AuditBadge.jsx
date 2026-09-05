import { useEffect, useState } from "react";
import { api } from "../api/client";

/**
 * Lightweight proof-of-concept indicator for the tamper-evident audit chain.
 * Calls GET /audit/verify once on load. Not a page -- just a header chip.
 */
export default function AuditBadge() {
  const [state, setState] = useState({ status: "loading", data: null });

  useEffect(() => {
    let alive = true;
    api
      .auditVerify()
      .then((data) => alive && setState({ status: "done", data }))
      .catch(() => alive && setState({ status: "error", data: null }));
    return () => {
      alive = false;
    };
  }, []);

  if (state.status === "loading") {
    return <span className="text-xs text-slate-400">Checking audit trail…</span>;
  }
  if (state.status === "error") {
    return null; // a transient network error shouldn't look like tampering
  }

  const { valid, entries_checked, broken_at } = state.data;
  if (valid) {
    return (
      <span
        className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700 ring-1 ring-inset ring-emerald-600/20"
        title={`${entries_checked.toLocaleString()} scoring events, SHA-256 hash-chained and re-verified`}
      >
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
        Audit trail verified ✓
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full bg-red-50 px-2 py-0.5 text-xs font-medium text-red-700 ring-1 ring-inset ring-red-600/20"
      title={`Chain broken at entry #${broken_at}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-red-500" />
      Audit trail tampered — broken at #{broken_at}
    </span>
  );
}
