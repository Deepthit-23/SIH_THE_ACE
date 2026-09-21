import { useEffect, useState } from "react";
import { api } from "../api/client";
import { saveSession } from "../lib/session";

// Documented demonstration accounts (see README). Choosing one fills the form; nothing is prefilled.
const DEMOS = [
  { label: "Ministry", user: "ministry_demo", pw: "DemoMinistry!2026" },
  { label: "State", user: "state_demo", pw: "DemoState!2026" },
  { label: "District", user: "district_demo", pw: "DemoDistrict!2026" },
  { label: "MP", user: "mp_demo", pw: "DemoMP!2026" },
];

/** The tool's one deliberate motion: a figure counts up once on load, then rests on its exact value.
 *  Skipped entirely for people who ask for reduced motion. */
function useCountUp(target, ms = 1400) {
  const [v, setV] = useState(0);
  useEffect(() => {
    if (target === null || target === undefined) return undefined;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      setV(target);
      return undefined;
    }
    let raf;
    let t0;
    const step = (t) => {
      t0 ??= t;
      const p = Math.min(1, (t - t0) / ms);
      setV(target * (1 - Math.pow(1 - p, 4)));   // ease-out: fast start, settles
      raf = p < 1 ? requestAnimationFrame(step) : undefined;
    };
    raf = requestAnimationFrame(step);
    return () => raf && cancelAnimationFrame(raf);
  }, [target, ms]);
  return v;
}

const inr = (n) => Math.round(n).toLocaleString("en-IN");

function Figure({ label, value, format, first }) {
  const n = useCountUp(value);
  return (
    <div className={`py-4 ${first ? "pr-6" : "border-l border-hairline px-6"}`}>
      <dt className="label">{label}</dt>
      <dd className="fig mt-2 text-[28px] font-medium leading-none text-ink">
        {value === null ? "-" : format(n)}
      </dd>
    </div>
  );
}

/** Three real national figures from the public exports, set as one ruled line (a register), not as cards. */
function Register() {
  const [s, setS] = useState({ status: "loading", data: null });
  useEffect(() => {
    let alive = true;
    api.publicSummary().then((d) => alive && setS({ status: "ok", data: d })).catch(() => alive && setS({ status: "error", data: null }));
    return () => { alive = false; };
  }, []);
  if (s.status === "error") return null;          // no invented numbers: if the feed is down, the strip is simply absent
  const d = s.data;
  const asOf = d ? new Date(d.as_of).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" }) : "";
  return (
    <div className="mt-10">
      <dl className="grid grid-cols-3 border-y border-ink">
        <Figure first label="Allocated" value={d ? d.allocated_amount / 1e7 : null} format={(n) => `₹${inr(n)} Cr`} />
        <Figure label="Works tracked" value={d ? d.works_tracked : null} format={inr} />
        <Figure label="MPs covered" value={d ? d.mps_covered : null} format={inr} />
      </dl>
      <p className="mt-2.5 text-xs text-ink-faint">
        {d ? `Public MPLADS exports, snapshot of ${asOf}.` : " "}
      </p>
    </div>
  );
}

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
      setError(err.message.replace(/^\d+ — /, ""));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex items-center gap-4 bg-ink px-6 py-2.5 text-surface">
        <span className="text-[15px] font-semibold">MPLAD Anomaly and Fraud Detection</span>
        <span className="hidden border-l border-surface/25 pl-4 text-xs text-surface/65 md:inline">
          Ministry of Statistics and Programme Implementation
        </span>
      </header>

      <main className="mx-auto grid w-full max-w-[1120px] flex-1 content-start gap-x-16 gap-y-12 px-8 py-16 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <section>
          <h1 className="text-[28px] font-semibold leading-tight">Audit register for MPLADS works</h1>
          <p className="mt-3 max-w-[48ch] text-ink-soft">
            Recommended and completed works under the MP Local Area Development Scheme, scored by a rule engine and an
            anomaly model. Every score and every review is written to a tamper-evident log.
          </p>
          <Register />
        </section>

        <section className="self-start border border-hairline bg-surface p-7">
          <h2 className="text-lg font-semibold">Sign in</h2>
          <form className="mt-5 space-y-4" onSubmit={submit}>
            <div>
              <label htmlFor="username" className="label">Username</label>
              <input id="username" className="field mt-1" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
            </div>
            <div>
              <label htmlFor="password" className="label">Password</label>
              <input id="password" type="password" className="field mt-1" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
            </div>
            {error && <p className="border-l-[3px] border-high bg-high/10 px-3 py-2 text-sm">{error}</p>}
            <button disabled={busy || !username || !password} className="btn-primary w-full">
              {busy ? "Signing in" : "Sign in"}
            </button>
          </form>

          <div className="mt-6 border-t border-hairline pt-4">
            <p className="text-xs text-ink-soft">Demonstration accounts. Choose one to fill the form.</p>
            <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1">
              {DEMOS.map((d) => (
                <button
                  key={d.user}
                  type="button"
                  onClick={() => { setUsername(d.user); setPassword(d.pw); }}
                  className="text-sm text-ink underline decoration-hairline underline-offset-4 hover:decoration-ink"
                >
                  {d.label}
                </button>
              ))}
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
