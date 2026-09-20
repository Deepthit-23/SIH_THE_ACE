// Session helpers: the token plus the profile returned by /auth/login. The profile is
// display-only (role banner, nav). Every permission is enforced by the backend.
const KEYS = ["mplad_token", "mplad_role", "mplad_scope", "mplad_profile"];

export const ROLE_LABEL = {
  ministry: "Ministry (national)",
  state_nodal: "State nodal officer",
  district_authority: "District authority",
  mp_self: "MP (own portfolio)",
};

export function loadSession() {
  try {
    if (!localStorage.getItem("mplad_token")) return null;
    const p = JSON.parse(localStorage.getItem("mplad_profile") || "null");
    if (p?.role) return p;
  } catch {
    /* corrupt profile: force a fresh sign-in */
  }
  clearSession();
  return null;
}

export function saveSession(r) {
  const profile = { username: r.username, role: r.role, scope_value: r.scope_value, scope_label: r.scope_label };
  localStorage.setItem("mplad_token", r.access_token);
  localStorage.setItem("mplad_role", r.role);
  localStorage.setItem("mplad_profile", JSON.stringify(profile));
  return profile;
}

export function clearSession() {
  KEYS.forEach((k) => localStorage.removeItem(k));
}
