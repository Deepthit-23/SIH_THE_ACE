"""RBAC: authentication is mandatory and scope is enforced SERVER-SIDE.

These tests try to break scoping (guessing IDs, filtering to other states, hitting
aggregate/pattern/meta endpoints, exporting) rather than just checking happy paths.
"""

import pytest
from sqlalchemy import text

from app.database import engine
from app.main import app

FORBIDDEN = {"is_synthetic_anomaly", "anomaly_type"}
PUBLIC = {"/", "/health", "/auth/login", "/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


def _sql(q, **p):
    with engine.connect() as c:
        return c.execute(text(q), p).all()


# ---- authentication -------------------------------------------------------
def _protected_routes():
    seen = set()
    for r in app.routes:
        path = getattr(r, "path", None)
        if not path or path in PUBLIC:
            continue
        for m in getattr(r, "methods", set()) - {"HEAD", "OPTIONS"}:
            seen.add((m, path))
    return sorted(seen)


def test_every_non_public_route_requires_a_token(client):
    """Walk the app's own route table so a newly added router can't ship unauthenticated."""
    routes = _protected_routes()
    assert len(routes) >= 15  # sanity: we really are walking the API
    for method, path in routes:
        url = path.replace("{project_id}", "1").replace("{district}", "X").replace("{vendor}", "X")
        r = client.request(method, url, json={} if method in {"PUT", "POST"} else None)
        assert r.status_code == 401, f"{method} {path} answered {r.status_code} without a token"


def test_garbage_and_expired_tokens_are_rejected(client):
    assert client.get("/risk-scores", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/risk-scores", headers={"Authorization": "Basic abc"}).status_code == 401


def test_bad_login(client):
    assert client.post("/auth/login", json={"username": "state_demo", "password": "wrong"}).status_code == 401
    assert client.post("/auth/login", json={"username": "nobody", "password": "x"}).status_code == 401


def test_token_carries_role_and_scope(client):
    r = client.post("/auth/login", json={"username": "state_demo", "password": "DemoState!2026"}).json()
    assert r["role"] == "state_nodal" and r["scope_value"] == "Telangana"
    assert r["scope_label"] == "Telangana"


# ---- scope on lists -------------------------------------------------------
def test_state_user_only_sees_their_state(client, state_user, ministry, has_data):
    mine = client.get("/risk-scores", params={"limit": 200}, headers=state_user).json()
    assert mine["total"] > 0
    assert {i["state"] for i in mine["items"]} == {"Telangana"}
    nat = client.get("/risk-scores", params={"limit": 1}, headers=ministry).json()["total"]
    assert mine["total"] < nat


def test_filtering_to_another_state_returns_nothing_not_that_states_data(client, state_user, has_data):
    other = _sql("SELECT state FROM projects WHERE state NOT ILIKE 'Telangana' LIMIT 1")[0][0]
    r = client.get("/risk-scores", params={"state": other}, headers=state_user).json()
    assert r["total"] == 0 and r["items"] == []
    r2 = client.get("/projects", params={"state": other}, headers=state_user).json()
    assert r2["total"] == 0


def test_search_cannot_reach_outside_scope(client, state_user, has_data):
    # an MP name that certainly exists, but only outside Telangana
    name = _sql("SELECT mp_name FROM projects WHERE state NOT ILIKE 'Telangana' LIMIT 1")[0][0]
    r = client.get("/risk-scores", params={"q": name}, headers=state_user).json()
    assert all(i["state"] == "Telangana" for i in r["items"])


def test_district_user_only_sees_their_district(client, district_user, has_data):
    r = client.get("/risk-scores", params={"limit": 200}, headers=district_user).json()
    assert r["total"] > 0
    assert {(i["district"] or "").upper() for i in r["items"]} == {"HYDERABAD"}


def test_mp_user_only_sees_their_own_portfolio(client, mp_user, has_data):
    r = client.get("/risk-scores", params={"limit": 200}, headers=mp_user).json()
    assert r["total"] > 0, "mp_demo scope must match real data (exact mp_name)"
    assert {i["mp_name"] for i in r["items"]} == {"Dr. Abhishek Manu Singhvi (2026-32)"}


# ---- scope on single records (ID guessing) ---------------------------------
def test_guessing_an_id_outside_scope_is_forbidden(client, state_user, district_user, mp_user, has_data):
    out_state = _sql("SELECT id FROM projects WHERE state NOT ILIKE 'Telangana' LIMIT 1")[0][0]
    out_district = _sql(
        "SELECT id FROM projects WHERE state ILIKE 'Telangana' AND district NOT ILIKE 'HYDERABAD' LIMIT 1")[0][0]
    out_mp = _sql("SELECT id FROM projects WHERE mp_name <> 'Dr. Abhishek Manu Singhvi (2026-32)' LIMIT 1")[0][0]
    for headers, pid in ((state_user, out_state), (district_user, out_district), (mp_user, out_mp)):
        assert client.get(f"/projects/{pid}", headers=headers).status_code == 403
        assert client.get(f"/projects/{pid}/case", headers=headers).status_code == 403
        assert client.get(f"/projects/{pid}/case/history", headers=headers).status_code == 403


def test_a_nonexistent_id_is_404_for_everyone(client, state_user, ministry):
    for h in (state_user, ministry):
        assert client.get("/projects/999999999", headers=h).status_code == 404


# ---- scope on aggregates / patterns / meta / export -----------------------
def test_meta_summary_is_scoped(client, state_user, district_user, ministry, has_data):
    nat = client.get("/meta/summary", headers=ministry).json()
    st = client.get("/meta/summary", headers=state_user).json()
    assert st["scope_label"] == "Telangana"
    assert st["projects_scored"] == _sql("SELECT count(*) FROM projects WHERE state ILIKE 'Telangana'")[0][0]
    assert st["allocated_amount"] < nat["allocated_amount"]
    d = client.get("/meta/summary", headers=district_user).json()
    assert d["projects_scored"] == _sql("SELECT count(*) FROM projects WHERE district ILIKE 'HYDERABAD'")[0][0]
    assert d["financials_available"] is False and d["allocated_amount"] is None  # no district grain


def test_meta_filters_are_scoped(client, state_user, ministry, has_data):
    assert client.get("/meta/filters", headers=state_user).json()["states"] == ["Telangana"]
    assert len(client.get("/meta/filters", headers=ministry).json()["states"]) > 10


def test_district_rankings_are_scoped(client, state_user, district_user, has_data):
    st_keys = {i["key"] for i in client.get("/patterns/districts", params={"limit": 100}, headers=state_user).json()["items"]}
    tel = {r[0].upper() for r in _sql("SELECT DISTINCT district FROM projects WHERE state ILIKE 'Telangana' AND district IS NOT NULL")}
    assert st_keys - {"(unknown)"} <= tel
    d_keys = [i["key"] for i in client.get("/patterns/districts", headers=district_user).json()["items"]]
    assert d_keys == ["HYDERABAD"]


def test_district_drilldown_outside_scope_is_not_found(client, state_user, district_user, has_data):
    other = _sql("SELECT district FROM projects WHERE state NOT ILIKE 'Telangana' AND district IS NOT NULL LIMIT 1")[0][0]
    assert client.get(f"/districts/{other}/pattern", headers=state_user).status_code == 404
    assert client.get("/districts/WARANGAL/pattern", headers=district_user).status_code == 404
    assert client.get("/districts/HYDERABAD/pattern", headers=district_user).status_code == 200


def test_contractor_patterns_do_not_leak_other_states(client, state_user, ministry, has_data):
    # a vendor that only ever transacted outside Telangana
    row = _sql(
        "SELECT vendor FROM vendor_transactions GROUP BY vendor "
        "HAVING bool_and(state NOT ILIKE 'Telangana') AND count(*) >= 20 LIMIT 1")
    assert row, "need an out-of-state-only vendor for this test"
    v = row[0][0]
    assert client.get(f"/contractors/{v}/pattern", headers=ministry).status_code == 200
    assert client.get(f"/contractors/{v}/pattern", headers=state_user).status_code == 404
    ranked = {i["key"] for i in client.get("/patterns/contractors", params={"limit": 100}, headers=state_user).json()["items"]}
    assert v not in ranked


def test_csv_export_is_scoped_and_has_no_synthetic_columns(client, state_user, ministry, has_data):
    r = client.get("/risk-scores/export.csv", params={"min_score": 50}, headers=state_user)
    assert r.status_code == 200
    lines = r.text.strip().splitlines()
    header = lines[0].split(",")
    assert not FORBIDDEN & set(header)
    assert "is_synthetic_anomaly" not in r.text and "anomaly_type" not in r.text
    st_idx = header.index("state")
    import csv, io
    rows = list(csv.reader(io.StringIO(r.text)))[1:]
    assert rows and {row[st_idx] for row in rows} == {"Telangana"}


def test_audit_verify_needs_auth_but_any_role_may_call_it(client, state_user, mp_user, has_data):
    assert client.get("/audit/verify").status_code == 401
    for h in (state_user, mp_user):
        assert client.get("/audit/verify", headers=h).status_code == 200


# ---- synthetic labels never leak, for ANY role, from ANY endpoint ----------
@pytest.mark.parametrize("role", ["ministry", "state_user", "district_user", "mp_user"])
def test_no_synthetic_label_in_any_payload_for_any_role(role, request, client, has_data):
    headers = request.getfixturevalue(role)
    pid = client.get("/risk-scores", params={"limit": 1}, headers=headers).json()["items"]
    paths = [
        "/risk-scores?limit=25", "/meta/summary", "/meta/filters", "/patterns/districts",
        "/patterns/contractors", "/cases", "/audit/verify", "/auth/me", "/projects?limit=25",
    ]
    if pid:
        paths += [f"/projects/{pid[0]['id']}", f"/projects/{pid[0]['id']}/case",
                  f"/projects/{pid[0]['id']}/case/history"]
    for p in paths:
        r = client.get(p, headers=headers)
        assert r.status_code == 200, f"{p} -> {r.status_code}"
        assert FORBIDDEN.isdisjoint(set(_keys(r.json()))), f"synthetic label leaked in {p}"


def test_recent_window_narrows_and_stays_in_scope(client, state_user, ministry, has_data):
    if not has_data:
        pytest.skip("no data loaded")
    full = client.get("/risk-scores?limit=200", headers=state_user).json()
    recent = client.get("/risk-scores?limit=200&recent_days=90", headers=state_user).json()
    assert recent["total"] <= full["total"]
    scope = client.get("/auth/me", headers=state_user).json()["scope_value"]
    assert all(i["state"].lower() == scope.lower() for i in recent["items"])
    nat = client.get("/risk-scores?limit=1&recent_days=90", headers=ministry).json()
    assert nat["total"] >= recent["total"]
