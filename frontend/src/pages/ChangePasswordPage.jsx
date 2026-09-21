import { useState } from "react";
import { api } from "../api/client";
import { updateProfile } from "../lib/session";

const MIN = 8;

/** Full-screen gate shown while the account still has must_change_password set.
 *  The backend blocks every other endpoint until this succeeds; this is just the way out. */
export default function ChangePasswordPage({ session, onDone, onLogout }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const problem =
    next.length > 0 && next.length < MIN
      ? `Use at least ${MIN} characters.`
      : confirm && next !== confirm
        ? "The two new passwords don't match."
        : next && next === current
          ? "The new password must differ from the temporary one."
          : "";

  async function submit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      onDone(updateProfile(await api.changePassword(current, next)));
    } catch (err) {
      setError(err.message.replace(/^\d+ — /, ""));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto mt-24 max-w-sm rounded border border-hairline bg-surface p-6">
      <h1 className="text-lg font-semibold">Set a new password</h1>
      <p className="mt-1 text-sm text-ink-soft">
        Signed in as <span className="font-medium text-ink">{session.username}</span>. Your account was
        created with a temporary password; choose your own to continue.
      </p>
      <form className="mt-4 space-y-3" onSubmit={submit}>
        <input className="w-full rounded border p-2" type="password" placeholder="Temporary password"
          value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" />
        <input className="w-full rounded border p-2" type="password" placeholder={`New password (min ${MIN})`}
          value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" />
        <input className="w-full rounded border p-2" type="password" placeholder="Confirm new password"
          value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" />
        {(problem || error) && <p className="text-sm text-high">{problem || error}</p>}
        <button
          disabled={busy || !current || !next || !!problem || next !== confirm}
          className="w-full rounded bg-ink p-2 text-surface disabled:opacity-50"
        >
          {busy ? "Saving…" : "Change password and continue"}
        </button>
      </form>
      <button onClick={onLogout} className="mt-4 text-xs text-ink-soft underline">Sign out</button>
    </main>
  );
}
