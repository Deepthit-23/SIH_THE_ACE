// Thin fetch wrapper.
// - dev: calls "/api/*", proxied to the backend by Vite (see vite.config.js)
// - prod: set VITE_API_BASE to the deployed backend origin (e.g. https://api.onrender.com)
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
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = "invalid request";
    } catch {
      /* non-JSON error body */
    }
    throw new Error(`${res.status} — ${detail}`);
  }
  return res.status === 204 ? null : res.json();
}

export const api = {
  base: BASE,
  qs,
  health: () => request("/health"),
  filters: () => request("/meta/filters"),
  summary: () => request("/meta/summary"),
  auditVerify: () => request("/audit/verify"),

  riskScores: (params) => request(`/risk-scores${qs(params)}`),
  exportCsvUrl: (params) => `${BASE}/risk-scores/export.csv${qs(params)}`,
  project: (id) => request(`/projects/${id}`),

  getCase: (id) => request(`/projects/${id}/case`),
  setCase: (id, body) =>
    request(`/projects/${id}/case`, { method: "PUT", body: JSON.stringify(body) }),
  caseHistory: (id) => request(`/projects/${id}/case/history`),
  cases: (params) => request(`/cases${qs(params)}`),

  rankDistricts: (params) => request(`/patterns/districts${qs(params)}`),
  rankContractors: (params) => request(`/patterns/contractors${qs(params)}`),
  districtPattern: (name, params) =>
    request(`/districts/${encodeURIComponent(name)}/pattern${qs(params)}`),
  contractorPattern: (name) =>
    request(`/contractors/${encodeURIComponent(name)}/pattern`),
};
