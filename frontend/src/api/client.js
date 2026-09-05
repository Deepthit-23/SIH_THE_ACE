// Thin fetch wrapper. All calls go through the Vite "/api" proxy to FastAPI.
const BASE = "/api";

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(`${res.status} ${detail}`);
  }
  return res.json();
}

export const api = {
  health: () => request("/health"),
  listProjects: ({ limit = 50, offset = 0 } = {}) =>
    request(`/projects?limit=${limit}&offset=${offset}`),
  getProject: (id) => request(`/projects/${id}`),
};
