// Thin fetch wrapper.
// - dev: calls "/api/*", proxied to the backend by Vite (see vite.config.js)
// - prod: set VITE_API_BASE to the deployed backend origin (e.g. https://api.onrender.com)
import { clearSession } from "../lib/session";

const BASE = import.meta.env.VITE_API_BASE || "/api";

function qs(params = {}) {
  const s = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") s.append(k, v);
  }
  const str = s.toString();
  return str ? `?${str}` : "";
}

async function request(path, opts = {}) {
  const token = localStorage.getItem("mplad_token");
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    ...opts,
  });
  if (res.status === 401 && !path.startsWith("/auth/login")) {
    // expired / invalid token: drop the session and return to the login page
    clearSession();
    window.location.reload();
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = "invalid request";
    } catch {
      /* non-JSON error body */
    }
    if (res.status === 403 && detail === "password_change_required") window.location.reload();
    throw new Error(`${res.status} — ${detail}`);
  }
  return res.status === 204 ? null : res.json();
}

export const api = {
  base: BASE,
  qs,
  health: () => request("/health"),
  login: (username, password) => request("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),
  me: () => request("/auth/me"),
  changePassword: (current_password, new_password) =>
    request("/auth/change-password", { method: "POST", body: JSON.stringify({ current_password, new_password }) }),

  // Ministry-only user management (the backend enforces the role; the UI just hides it)
  adminUsers: () => request("/admin/users"),
  createUser: (body) => request("/admin/users", { method: "POST", body: JSON.stringify(body) }),
  patchUser: (id, body) => request(`/admin/users/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  scopeOptions: (kind, q) => request(`/admin/scope-options${qs({ kind, q })}`),
  publicSummary: () => request("/meta/public-summary"),   // unauthenticated: the sign-in page runs before login
  filters: () => request("/meta/filters"),
  summary: () => request("/meta/summary"),
  auditVerify: () => request("/audit/verify"),
  auditRecent: (limit = 6) => request(`/audit/recent${qs({ limit })}`),

  riskScores: (params) => request(`/risk-scores${qs(params)}`),
  // The export needs the bearer token, so it can't be a plain <a href>.
  downloadCsv: async (params) => {
    const token = localStorage.getItem("mplad_token");
    const res = await fetch(`${BASE}/risk-scores/export.csv${qs(params)}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error(`${res.status} — export failed`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `mplad_flagged_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
  project: (id) => request(`/projects/${id}`),

  getCase: (id) => request(`/projects/${id}/case`),
  setCase: (id, body) =>
    request(`/projects/${id}/case`, { method: "PUT", body: JSON.stringify(body) }),
  caseHistory: (id) => request(`/projects/${id}/case/history`),
  cases: (params) => request(`/cases${qs(params)}`),

  stateAggregates: (params) => request(`/patterns/states${qs(params)}`),
  contractorNetwork: (params) => request(`/patterns/network${qs(params)}`),
  rankDistricts: (params) => request(`/patterns/districts${qs(params)}`),
  rankContractors: (params) => request(`/patterns/contractors${qs(params)}`),
  districtPattern: (name, params) =>
    request(`/districts/${encodeURIComponent(name)}/pattern${qs(params)}`),
  contractorPattern: (name) =>
    request(`/contractors/${encodeURIComponent(name)}/pattern`),
};
