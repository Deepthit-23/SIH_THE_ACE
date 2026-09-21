import { Fragment, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { useAsync } from "../hooks/useAsync";
import { Empty, ErrorBox, Loading } from "../components/StateMessage";
import { ROLE_LABEL } from "../lib/session";

const ROLES = ["state_nodal", "district_authority", "mp_self", "ministry"];
const INPUT = "rounded border border-hairline bg-surface px-2 py-1.5 text-sm focus:border-ink-faint focus:outline-none";
const cleanErr = (e) => String(e?.message || e).replace(/^\d+ — /, "");

/** Random temporary password (no look-alike characters). Only ever shown to the admin, once. */
function generatePassword(len = 12) {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789";
  const bytes = crypto.getRandomValues(new Uint32Array(len));
  return Array.from(bytes, (b) => chars[b % chars.length]).join("") + "!7";
}

/** Scope input that adapts to the selected role. `onChange(value, state?)`: a district scope is a
 *  (state, district) pair because district names repeat across states (e.g. Bilaspur in HP and Chhattisgarh). */
function ScopeField({ role, value, state, onChange }) {
  const kind = { state_nodal: "state", district_authority: "district", mp_self: "mp" }[role];
  const options = useAsync(() => (kind && kind !== "mp" ? api.scopeOptions(kind) : Promise.resolve([])), [kind]);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState([]);

  useEffect(() => {
    if (kind !== "mp" || query.trim().length < 2) { setHits([]); return undefined; }
    const t = setTimeout(() => api.scopeOptions("mp", query.trim()).then(setHits).catch(() => setHits([])), 250);
    return () => clearTimeout(t);
  }, [kind, query]);

  if (role === "ministry") {
    return <p className="rounded border border-hairline bg-canvas px-2 py-1.5 text-sm text-ink-soft">National — no scope</p>;
  }
  if (kind === "mp") {
    return (
      <div className="relative">
        {value ? (
          <div className="flex items-center gap-2 rounded border border-hairline bg-canvas px-2 py-1.5 text-sm">
            <span className="truncate">{value}</span>
            <button type="button" onClick={() => { onChange(""); setQuery(""); }} className="ml-auto text-xs text-ink-soft underline">change</button>
          </div>
        ) : (
          <>
            <input className={`${INPUT} w-full`} placeholder="Search MP name (2+ letters)…" value={query}
              onChange={(e) => setQuery(e.target.value)} />
            {hits.length > 0 && (
              <ul className="absolute z-10 mt-1 max-h-56 w-full overflow-auto rounded border border-hairline bg-surface ">
                {hits.map((h) => (
                  <li key={h.value}>
                    <button type="button" onClick={() => onChange(h.value)}
                      className="block w-full px-2 py-1.5 text-left text-sm hover:bg-canvas">{h.label}</button>
                  </li>
                ))}
              </ul>
            )}
            {query.trim().length >= 2 && hits.length === 0 && <p className="mt-1 text-xs text-ink-faint">No matching MP.</p>}
          </>
        )}
      </div>
    );
  }
  return (
    <select
      className={`${INPUT} w-full`}
      value={kind === "district" ? (value ? `${state}||${value}` : "") : value}
      onChange={(e) => {
        const v = e.target.value;
        if (kind === "district") { const [st, d] = v ? v.split("||") : ["", ""]; onChange(d, st); } else onChange(v);
      }}
      disabled={options.status !== "success"}
    >
      <option value="">{options.status === "loading" ? "Loading…" : `Select a ${kind}…`}</option>
      {(options.data ?? []).map((o) => {
        const key = kind === "district" ? `${o.state}||${o.value}` : o.value;
        return <option key={key} value={key}>{o.label}</option>;
      })}
    </select>
  );
}

function CreateUserForm({ onCreated }) {
  const [username, setUsername] = useState("");
  const [role, setRole] = useState("state_nodal");
  const [scope, setScope] = useState("");
  const [scopeState, setScopeState] = useState("");        // district accounts only
  const [password, setPassword] = useState(() => generatePassword());
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);

  const needsScope = role !== "ministry";
  const ready = /^[A-Za-z0-9][A-Za-z0-9._@-]{2,63}$/.test(username) && password.length >= 8
    && (!needsScope || scope) && (role !== "district_authority" || scopeState);

  async function submit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const u = await api.createUser({ username, role, scope_value: needsScope ? scope : null,
        scope_state: role === "district_authority" ? scopeState : null, temp_password: password });
      setDone({ username: u.username, password });
      setUsername(""); setScope(""); setScopeState(""); setPassword(generatePassword());
      onCreated();
    } catch (err) {
      setError(cleanErr(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3 rounded border border-hairline bg-surface p-4">
      <h3 className="text-sm font-semibold">Create user</h3>
      <div className="grid gap-3 md:grid-cols-2">
        <label className="flex flex-col gap-1 text-xs text-ink-soft">
          Username
          <input className={INPUT} value={username} onChange={(e) => setUsername(e.target.value.trim())}
            placeholder="e.g. ka_nodal_1" autoComplete="off" />
        </label>
        <label className="flex flex-col gap-1 text-xs text-ink-soft">
          Role
          <select className={INPUT} value={role} onChange={(e) => { setRole(e.target.value); setScope(""); setScopeState(""); }}>
            {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-ink-soft">
          Scope {role === "state_nodal" ? "(state)" : role === "district_authority" ? "(district)" : role === "mp_self" ? "(MP)" : ""}
          <ScopeField role={role} value={scope} state={scopeState}
            onChange={(v, st) => { setScope(v); setScopeState(st ?? ""); }} />
        </label>
        <label className="flex flex-col gap-1 text-xs text-ink-soft">
          Temporary password
          <div className="flex gap-2">
            <input className={`${INPUT} w-full font-mono`} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="off" />
            <button type="button" onClick={() => setPassword(generatePassword())}
              className="shrink-0 rounded border border-hairline px-2 text-xs text-ink-soft hover:bg-canvas">Generate</button>
          </div>
        </label>
      </div>
      {error && <p className="text-sm text-high">{error}</p>}
      {done && (
        <div className="rounded border border-low/40 bg-low/10 p-3 text-sm text-low">
          Created <b>{done.username}</b>. Temporary password: <code className="rounded bg-surface px-1 font-mono">{done.password}</code>
          <p className="mt-1 text-xs">Shown once. Share it securely; the user must set their own password at first sign-in.</p>
        </div>
      )}
      <button disabled={!ready || busy} className="rounded bg-ink px-4 py-1.5 text-sm text-surface disabled:opacity-50">
        {busy ? "Creating…" : "Create user"}
      </button>
    </form>
  );
}

function ResetPanel({ user, onClose, onDone }) {
  const [pw, setPw] = useState(() => generatePassword());
  const [error, setError] = useState("");
  const [shown, setShown] = useState(null);

  async function apply() {
    setError("");
    try {
      await api.patchUser(user.id, { reset_password: pw });
      setShown(pw);
      onDone();
    } catch (err) {
      setError(cleanErr(err));
    }
  }
  return (
    <div className="flex flex-wrap items-center gap-2 bg-canvas px-3 py-2 text-sm">
      {shown ? (
        <>
          <span>New temporary password for <b>{user.username}</b>: <code className="rounded bg-surface px-1 font-mono">{shown}</code></span>
          <span className="text-xs text-ink-soft">(shown once; they must change it at next sign-in)</span>
          <button onClick={onClose} className="ml-auto text-xs underline">Close</button>
        </>
      ) : (
        <>
          <span className="text-xs text-ink-soft">Reset password for {user.username}:</span>
          <input className={`${INPUT} font-mono`} value={pw} onChange={(e) => setPw(e.target.value)} />
          <button onClick={() => setPw(generatePassword())} className="rounded border border-hairline px-2 py-1 text-xs">Generate</button>
          <button onClick={apply} disabled={pw.length < 8} className="rounded bg-ink px-3 py-1 text-xs text-surface disabled:opacity-50">Apply</button>
          <button onClick={onClose} className="text-xs underline">Cancel</button>
          {error && <span className="text-xs text-high">{error}</span>}
        </>
      )}
    </div>
  );
}

export default function AdminUsersPage({ session }) {
  const { status, data, error, reload } = useAsync(() => api.adminUsers(), []);
  const [resetting, setResetting] = useState(null);
  const [rowError, setRowError] = useState("");

  const users = useMemo(() => data ?? [], [data]);

  async function toggleActive(u) {
    setRowError("");
    if (u.is_active && !window.confirm(`Deactivate ${u.username}? Their sessions end immediately.`)) return;
    try {
      await api.patchUser(u.id, { is_active: !u.is_active });
      reload();
    } catch (err) {
      setRowError(`${u.username}: ${cleanErr(err)}`);
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">User management</h2>
        <p className="text-sm text-ink-soft">
          Ministry only. Every change here is written to the tamper-evident audit chain as an admin action.
        </p>
      </div>

      <CreateUserForm onCreated={reload} />

      {status === "loading" && <Loading label="Loading users…" />}
      {status === "error" && <ErrorBox error={error} onRetry={reload} />}
      {status === "success" && users.length === 0 && <Empty>No users.</Empty>}
      {rowError && <p className="text-sm text-high">{rowError}</p>}
      {status === "success" && users.length > 0 && (
        <div className="overflow-x-auto rounded border border-hairline bg-surface">
          <table className="min-w-full text-sm">
            <thead className="border-b border-hairline bg-canvas text-left text-xs font-medium text-ink-soft">
              <tr>
                <th className="px-3 py-2">Username</th><th className="px-3 py-2">Role</th>
                <th className="px-3 py-2">Scope</th><th className="px-3 py-2">Status</th>
                <th className="px-3 py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-hairline">
              {users.map((u) => {
                const self = u.username === session.username;
                return (
                  <Fragment key={u.id}>
                  <tr className={u.is_active ? "" : "bg-canvas text-ink-faint"}>
                    <td className="px-3 py-2 font-medium">{u.username}{self && <span className="ml-2 text-xs font-normal text-ink-faint">(you)</span>}</td>
                    <td className="px-3 py-2">{ROLE_LABEL[u.role] ?? u.role}</td>
                    <td className="px-3 py-2">{u.scope_label}</td>
                    <td className="px-3 py-2">
                      <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${u.is_active ? "bg-low/10 text-low" : "bg-canvas text-ink-soft"}`}>
                        {u.is_active ? "Active" : "Inactive"}
                      </span>
                      {u.must_change_password && (
                        <span className="ml-1 rounded bg-medium/10 px-1.5 py-0.5 text-[11px] font-medium text-ink">must change password</span>
                      )}
                    </td>
                    <td className="space-x-3 px-3 py-2 text-right">
                      <button onClick={() => setResetting(resetting === u.id ? null : u.id)} className="text-xs text-ink-soft underline">Reset password</button>
                      <button onClick={() => toggleActive(u)} disabled={self && u.is_active}
                        title={self && u.is_active ? "You cannot deactivate your own account" : ""}
                        className="text-xs text-ink-soft underline disabled:cursor-not-allowed disabled:opacity-40">
                        {u.is_active ? "Deactivate" : "Reactivate"}
                      </button>
                    </td>
                  </tr>
                  {resetting === u.id && (
                    <tr><td colSpan={5} className="p-0"><ResetPanel user={u} onClose={() => setResetting(null)} onDone={reload} /></td></tr>
                  )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
