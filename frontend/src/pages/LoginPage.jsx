import { useState } from "react";
import { api } from "../api/client";
import { saveSession } from "../lib/session";

// Documented demo accounts (see README). Clicking one fills the form; nothing is prefilled.
const DEMOS = [
  { label: "Ministry", user: "ministry_demo", pw: "DemoMinistry!2026" },
  { label: "State", user: "state_demo", pw: "DemoState!2026" },
  { label: "District", user: "district_demo", pw: "DemoDistrict!2026" },
  { label: "MP", user: "mp_demo", pw: "DemoMP!2026" },
];

export default function LoginPage({ onLogin }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      onLogin(saveSession(await api.login(username, password)));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto mt-24 max-w-sm rounded border border-slate-200 bg-white p-6">
      <h1 className="text-lg font-semibold">MPLAD secure sign in</h1>
      <p className="mt-1 text-sm text-slate-500">Sign in with your role account, or pick a demo account.</p>
      <div className="mt-3 flex flex-wrap gap-2">
        {DEMOS.map((d) => (
          <button
            key={d.user}
            type="button"
            onClick={() => { setUsername(d.user); setPassword(d.pw); }}
            className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
          >
            {d.label}
          </button>
        ))}
      </div>
      <form className="mt-4 space-y-3" onSubmit={submit}>
        <input className="w-full rounded border p-2" placeholder="Username" value={username}
          onChange={(e) => setUsername(e.target.value)} aria-label="Username" autoComplete="username" />
        <input className="w-full rounded border p-2" type="password" placeholder="Password" value={password}
          onChange={(e) => setPassword(e.target.value)} aria-label="Password" autoComplete="current-password" />
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button disabled={busy || !username || !password} className="w-full rounded bg-slate-800 p-2 text-white disabled:opacity-50">
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
