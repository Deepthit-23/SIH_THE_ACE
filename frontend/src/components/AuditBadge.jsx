import { useEffect, useState } from "react";
import { api } from "../api/client";

/**
 * Verdict on the whole audit hash-chain (GET /audit/verify). Sits on the ink top bar: a tier-coloured dot and
 * a plain sentence. The chain's structure is drawn separately by AuditChainWidget.
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

  if (state.status === "loading") return <span className="text-xs text-surface/60">Checking audit trail</span>;
  if (state.status === "error") return null; // a transient network error shouldn't look like tampering

  const { valid, entries_checked, broken_at } = state.data;
  return valid ? (
    <span
      className="inline-flex items-center gap-2 text-xs text-surface"
      title={`${entries_checked.toLocaleString("en-IN")} entries, SHA-256 hash-chained and re-verified`}
    >
      <span className="h-2 w-2 rounded-full bg-low" />
      Audit trail verified
    </span>
  ) : (
    <span className="inline-flex items-center gap-2 bg-high px-2 py-0.5 text-xs font-medium text-surface" title={`Chain broken at entry ${broken_at}`}>
      Audit trail broken at entry {broken_at}
    </span>
  );
}
