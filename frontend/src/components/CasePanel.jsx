import { useEffect, useState } from "react";
import { api } from "../api/client";
import { CASE_ORDER, CASE_STATUS, fmtDateTime, text } from "../lib/format";

/** Auditor workflow controls on the project detail view. */
export default function CasePanel({ projectId, initialStatus, initialNote, updatedAt }) {
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

  return (
    <div className="rounded border border-slate-200 bg-white p-5">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-800">Case status</h3>
        <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${CASE_STATUS[status].chip}`}>
          {CASE_STATUS[status].label}
        </span>
      </div>
      <p className="mb-3 mt-1 text-xs text-slate-500">
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
                ? "border-slate-800 bg-slate-800 text-white"
                : "border-slate-300 text-slate-600 hover:bg-slate-50")
            }
          >
            {CASE_STATUS[s].label}
          </button>
        ))}
      </div>

      <label className="mt-3 block text-xs text-slate-500">
        Note {needNote && <span className="text-red-600">(required to dismiss)</span>}
        <textarea
          rows={2}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder={
            needNote
              ? "e.g. false positive — legitimate cost variance, verified against tender docs"
              : "optional context for this decision"
          }
          className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm focus:border-slate-400 focus:outline-none"
        />
      </label>

      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}

      <div className="mt-3 flex items-center gap-2">
        <button
          disabled={busy || !dirty || (needNote && !note.trim())}
          onClick={save}
          className="rounded bg-slate-800 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
        >
          {busy ? "Saving…" : "Save decision"}
        </button>
        {dirty && !busy && (
          <button
            onClick={() => { setPending(null); setNote(initialNote || ""); }}
            className="text-xs text-slate-400 hover:text-slate-600"
          >
            Cancel
          </button>
        )}
      </div>

      {history.length > 0 && (
        <div className="mt-4 border-t border-slate-100 pt-3">
          <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-slate-400">
            Review history · in the audit chain
          </p>
          <ul className="space-y-1 text-xs text-slate-600">
            {history.map((h, i) => (
              <li key={i} className="flex justify-between gap-2">
                <span>
                  {CASE_STATUS[h.status]?.label || h.status}
                  {h.reviewer ? ` · ${h.reviewer}` : ""}
                </span>
                <span className="tabular-nums text-slate-400" title={h.payload_hash}>
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
