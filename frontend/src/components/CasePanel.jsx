import { useEffect, useState } from "react";
import { api } from "../api/client";
import { CASE_ORDER, CASE_STATUS, fmtDateTime, text } from "../lib/format";

/** Auditor workflow controls on the project detail view. */
export default function CasePanel({ projectId, initialStatus, initialNote, updatedAt }) {
  const role = localStorage.getItem("mplad_role");
  const [status, setStatus] = useState(initialStatus || "pending");
  const [note, setNote] = useState(initialNote || "");
  const [savedAt, setSavedAt] = useState(updatedAt || null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [history, setHistory] = useState([]);
  const [pending, setPending] = useState(null); // status the user picked but hasn't saved

  useEffect(() => {
    api.caseHistory(projectId).then(setHistory).catch(() => {});
  }, [projectId, savedAt]);

  const target = pending || status;
  const needNote = target === "dismissed";
  const dirty = pending !== null && (pending !== status || note !== (initialNote || ""));

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const res = await api.setCase(projectId, {
        status: target,
        note: note.trim() || null,
        reviewer: "auditor",
      });
      setStatus(res.status);
      setSavedAt(res.updated_at);
      setPending(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (role === "mp_self") return <div className="rounded border border-hairline bg-surface p-5 text-sm text-ink-soft">Case status: {CASE_STATUS[status].label}. MP accounts are read-only.</div>;
  return (
    <div className="rounded border border-hairline bg-surface p-5">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-ink">Case status</h3>
        <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${CASE_STATUS[status].chip}`}>
          {CASE_STATUS[status].label}
        </span>
      </div>
      <p className="mb-3 mt-1 text-xs text-ink-soft">
        {savedAt ? `Last updated ${fmtDateTime(savedAt)}` : "Not yet reviewed"}
      </p>

      <div className="flex flex-wrap gap-2">
        {CASE_ORDER.map((s) => (
          <button
            key={s}
            onClick={() => setPending(s)}
            className={
              "rounded border px-3 py-1.5 text-xs font-medium transition " +
              (target === s
                ? "border-ink-faint bg-ink text-surface"
                : "border-hairline text-ink-soft hover:bg-canvas")
            }
          >
            {CASE_STATUS[s].label}
          </button>
        ))}
      </div>

      <label className="mt-3 block text-xs text-ink-soft">
        Note {needNote && <span className="text-high">(required to dismiss)</span>}
        <textarea
          rows={2}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder={
            needNote
              ? "e.g. false positive — legitimate cost variance, verified against tender docs"
              : "optional context for this decision"
          }
          className="mt-1 w-full rounded border border-hairline px-2 py-1.5 text-sm focus:border-ink-faint focus:outline-none"
        />
      </label>

      {error && <p className="mt-2 text-xs text-high">{error}</p>}

      <div className="mt-3 flex items-center gap-2">
        <button
          disabled={busy || !dirty || (needNote && !note.trim())}
          onClick={save}
          className="rounded bg-ink px-3 py-1.5 text-xs font-medium text-surface disabled:opacity-40"
        >
          {busy ? "Saving…" : "Save decision"}
        </button>
        {dirty && !busy && (
          <button
            onClick={() => { setPending(null); setNote(initialNote || ""); }}
            className="text-xs text-ink-faint hover:text-ink-soft"
          >
            Cancel
          </button>
        )}
      </div>

      {history.length > 0 && (
        <div className="mt-4 border-t border-hairline pt-3">
          <p className="mb-1.5 text-[11px] font-medium text-ink-faint">
            Review history, recorded in the audit chain
          </p>
          <ul className="space-y-1 text-xs text-ink-soft">
            {history.map((h, i) => (
              <li key={i} className="flex justify-between gap-2">
                <span>
                  {CASE_STATUS[h.status]?.label || h.status}
                  {h.reviewer ? ` by ${h.reviewer}` : ""}
                </span>
                <span className="tabular-nums text-ink-faint" title={h.payload_hash}>
                  {fmtDateTime(h.timestamp)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
