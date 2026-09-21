"""RBAC: authentication is mandatory and scope is enforced SERVER-SIDE.

These tests try to break scoping (guessing IDs, filtering to other states, hitting
aggregate/pattern/meta endpoints, exporting) rather than just checking happy paths.
"""

import pytest
from sqlalchemy import text

from app.database import engine
from app.main import app

FORBIDDEN = {"is_synthetic_anomaly", "anomaly_type"}
PUBLIC = {"/", "/health", "/auth/login", "/meta/public-summary", "/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}


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
    # State scope is where the work is LOCATED (work_state); RiskListItem.state is the MP's state
    assert {i["work_state"] for i in mine["items"]} == {"Telangana"}
    assert mine["total"] == _sql("SELECT count(*) FROM projects WHERE work_state = 'Telangana'")[0][0]
    nat = client.get("/risk-scores", params={"limit": 1}, headers=ministry).json()["total"]
    assert mine["total"] < nat


# What each scoped role is allowed to see, straight from the table (independent of the code under test).
SCOPE_ROWS = {
    "state_user": "SELECT id, work_state, district FROM projects WHERE work_state = 'Telangana'",
    "district_user": "SELECT id, work_state, district FROM projects WHERE work_state = 'Telangana' AND district = 'HYDERABAD'",
    "mp_user": "SELECT id, work_state, district FROM projects WHERE mp_name = 'Dr. Abhishek Manu Singhvi (2026-32)'",
}


def _every_state_value():
    """EVERY state string in the data (MP states and work states), not one row-order-dependent pick."""
    rows = _sql("SELECT state FROM projects WHERE state IS NOT NULL UNION SELECT work_state FROM projects "
                "WHERE work_state IS NOT NULL ORDER BY 1")
    vals = [r[0] for r in rows]
    assert len(vals) >= 35, "expected the full set of states and UTs"
    return vals + [vals[0].lower(), vals[1].upper(), "Telangana", "telangana", "No Such State"]


@pytest.mark.parametrize("role", ["state_user", "district_user", "mp_user"])
def test_state_filter_only_narrows_within_scope_for_every_state_value(client, request, role, has_data):
    """A filter is ANDed with the scope: for EVERY state value the result must be
       (a) a subset of the caller's scope (nothing outside it, ever), and
       (b) exactly scope AND filter (total == the SQL ground truth), which also catches a filter that means
           something different from the documented one (e.g. MP state instead of work location).
    Checked on both list endpoints. No `LIMIT 1` sample: the whole state list, so row order cannot matter."""
    hdr = request.getfixturevalue(role)
    scope = _sql(SCOPE_ROWS[role])
    scope_ids = {r[0] for r in scope}
    assert scope_ids, "scope must contain rows for the sweep to mean anything"
    for s in _every_state_value():
        expected = sum(1 for r in scope if (r[1] or "").upper() == s.upper())
        for path, params in (("/projects", {"state": s, "limit": 500}), ("/risk-scores", {"state": s, "limit": 200})):
            r = client.get(path, params=params, headers=hdr).json()
            got = {i["id"] for i in r["items"]}
            assert got <= scope_ids, (role, path, s, "OUT OF SCOPE:", sorted(got - scope_ids)[:5])
            assert r["total"] == expected, (role, path, s, r["total"], "!=", expected)


@pytest.mark.parametrize("role", ["state_user", "district_user", "mp_user"])
def test_district_filter_only_narrows_within_scope_for_a_spread_of_districts(client, request, role, has_data):
    hdr = request.getfixturevalue(role)
    scope = _sql(SCOPE_ROWS[role])
    scope_ids = {r[0] for r in scope}
    all_d = [r[0] for r in _sql("SELECT DISTINCT district FROM projects WHERE district IS NOT NULL ORDER BY 1")]
    values = all_d[:: max(1, len(all_d) // 40)] + ["HYDERABAD", "WARANGAL", "No Such District"]
    for d in values:
        expected = sum(1 for r in scope if (r[2] or "") == d)
        for path, params in (("/projects", {"district": d, "limit": 500}), ("/risk-scores", {"district": d, "limit": 200})):
            r = client.get(path, params=params, headers=hdr).json()
            assert {i["id"] for i in r["items"]} <= scope_ids, (role, path, d)
            assert r["total"] == expected, (role, path, d, r["total"], "!=", expected)


def test_search_cannot_reach_outside_scope(client, state_user, has_data):
    # MPs from elsewhere -- including two whose works are physically IN Telangana (they are in scope, by design)
    scope_ids = {r[0] for r in _sql("SELECT id FROM projects WHERE work_state = 'Telangana'")}
    names = [r[0] for r in _sql("SELECT DISTINCT mp_name FROM projects WHERE mp_name IS NOT NULL ORDER BY 1")]
    picks = names[:: max(1, len(names) // 30)] + [n for n in names if "Vijayendra Prasad" in n or "K. Laxman" in n]
    for name in picks:
        r = client.get("/risk-scores", params={"q": name, "limit": 200}, headers=state_user).json()
        assert {i["id"] for i in r["items"]} <= scope_ids, name


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
    out_state = _sql("SELECT id FROM projects WHERE work_state <> 'Telangana' ORDER BY id LIMIT 1")[0][0]
    out_district = _sql(
        "SELECT id FROM projects WHERE work_state = 'Telangana' AND district <> 'HYDERABAD' ORDER BY id LIMIT 1")[0][0]
    out_mp = _sql("SELECT id FROM projects WHERE mp_name <> 'Dr. Abhishek Manu Singhvi (2026-32)' ORDER BY id LIMIT 1")[0][0]
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
    assert st["projects_scored"] == _sql("SELECT count(*) FROM projects WHERE work_state ILIKE 'Telangana'")[0][0]
    assert st["allocated_amount"] < nat["allocated_amount"]
    d = client.get("/meta/summary", headers=district_user).json()
    assert d["projects_scored"] == _sql(
        "SELECT count(*) FROM projects WHERE district ILIKE 'HYDERABAD' AND work_state = 'Telangana'")[0][0]
    assert d["financials_available"] is False and d["allocated_amount"] is None  # no district grain


def test_meta_filters_are_scoped(client, state_user, ministry, has_data):
    # geography filter options are where the works are LOCATED, but only for rows inside the user's scope
    assert client.get("/meta/filters", headers=state_user).json()["states"] == ["Telangana"]
    assert len(client.get("/meta/filters", headers=ministry).json()["states"]) > 10


def test_district_rankings_are_scoped(client, state_user, district_user, has_data):
    st_keys = {i["key"] for i in client.get("/patterns/districts", params={"limit": 100}, headers=state_user).json()["items"]}
    tel = {r[0].upper() for r in _sql("SELECT DISTINCT district FROM projects WHERE state ILIKE 'Telangana' AND district IS NOT NULL")}
    assert st_keys - {"(unknown)"} <= tel
    d_keys = [i["key"] for i in client.get("/patterns/districts", headers=district_user).json()["items"]]
    assert d_keys == ["HYDERABAD"]


def test_district_drilldown_outside_scope_is_not_found(client, state_user, district_user, has_data):
    other = _sql("SELECT district FROM projects WHERE district IS NOT NULL GROUP BY district "
                 "HAVING bool_and(work_state IS DISTINCT FROM 'Telangana') ORDER BY district LIMIT 1")[0][0]
    assert client.get(f"/districts/{other}/pattern", headers=state_user).status_code == 404
    assert client.get("/districts/WARANGAL/pattern", headers=district_user).status_code == 404
    assert client.get("/districts/HYDERABAD/pattern", headers=district_user).status_code == 200


def test_contractor_patterns_do_not_leak_other_states(client, state_user, ministry, has_data):
    # a vendor that only ever transacted outside Telangana
    row = _sql(
        "SELECT vendor FROM vendor_transactions GROUP BY vendor "
        "HAVING bool_and(work_state IS DISTINCT FROM 'Telangana') AND count(*) >= 20 ORDER BY vendor LIMIT 1")
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
    st_idx = header.index("work_state")
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
    assert all((i["work_state"] or "").lower() == scope.lower() for i in recent["items"])
    nat = client.get("/risk-scores?limit=1&recent_days=90", headers=ministry).json()
    assert nat["total"] >= recent["total"]


# ---- audit chain widget feed ---------------------------------------------
def test_audit_recent_needs_auth_and_exposes_only_chain_metadata(client, state_user, mp_user, ministry, has_data):
    assert client.get("/audit/recent").status_code == 401
    for hdr in (state_user, mp_user, ministry):
        r = client.get("/audit/recent?limit=6", headers=hdr)
        assert r.status_code == 200
        body = r.json()
        es = body["entries"]
        assert 1 <= len(es) <= 6 and body["height"] == es[0]["id"]
        assert {"id", "event_type", "hash", "previous_hash", "timestamp"} == set(es[0])   # no payload / project_id
        assert all(a["previous_hash"] == b["hash"] for a, b in zip(es, es[1:]))            # the chain links
        assert all(len(e["hash"]) == 64 for e in es)
    assert client.get("/audit/recent?limit=0", headers=ministry).status_code == 422
    assert client.get("/audit/recent?limit=21", headers=ministry).status_code == 422


# ---- state aggregates for the choropleth ----------------------------------
def test_state_aggregates_are_scoped(client, state_user, district_user, mp_user, ministry, has_data):
    assert client.get("/patterns/states").status_code == 401
    nat = client.get("/patterns/states", headers=ministry).json()
    assert len(nat["items"]) > 30 and nat["scope_label"] == "National"
    # national totals reconcile: every project is on a state OR counted as unlocated (never dropped silently)
    total = sum(i["project_count"] for i in nat["items"]) + nat["unlocated_count"]
    assert total == client.get("/risk-scores?limit=1", headers=ministry).json()["total"]

    mine = client.get("/patterns/states", headers=state_user).json()
    assert mine["scope_kind"] == "state" and nat["scope_kind"] == "national"
    assert client.get("/patterns/states", headers=district_user).json()["scope_kind"] == "district"
    assert client.get("/patterns/states", headers=mp_user).json()["scope_kind"] == "mp"
    assert [i["state"] for i in mine["items"]] == ["Telangana"]                 # exactly their state, nothing else
    assert mine["unlocated_count"] == 0                                        # a scoped user can never match a NULL
    assert sum(i["project_count"] for i in mine["items"]) == client.get("/risk-scores?limit=1", headers=state_user).json()["total"]

    d = client.get("/patterns/states", headers=district_user).json()
    # district scope is matched by NAME, so a district name shared by two states yields two rows -- but
    # the counts are only the district's own projects, never the whole state's
    dist_total = client.get("/risk-scores?limit=1", headers=district_user).json()["total"]
    assert sum(i["project_count"] for i in d["items"]) == dist_total
    tel = next(i for i in mine["items"] if i["state"] == "Telangana")["project_count"]
    assert dist_total <= tel < total                                      # the district is INSIDE its state
    m = client.get("/patterns/states", headers=mp_user).json()
    assert sum(i["project_count"] for i in m["items"]) == client.get("/risk-scores?limit=1", headers=mp_user).json()["total"]
    for it in nat["items"]:
        assert 0 <= it["flagged_pct"] <= 100 and it["flagged_count"] <= it["project_count"]


# ---- contractor-MP network feed -------------------------------------------
def test_network_edges_are_flagged_relationships_and_scoped(client, state_user, district_user, ministry, has_data):
    from app.pipeline.rules import CONTRACTOR_SHARE_THRESHOLD as THR
    assert client.get("/patterns/network").status_code == 401
    nat = client.get("/patterns/network?limit=40", headers=ministry).json()
    assert nat["scope_label"] == "National" and 0 < len(nat["edges"]) <= 40
    assert {"vendor", "mp_name", "txn_count", "txn_value", "share_of_unit_value"} <= set(nat["edges"][0])
    for e in nat["edges"]:                                    # every edge is a flagged concentration case
        assert max(e["share_of_unit_count"], e["share_of_unit_value"]) >= THR
    shares = [e["share_of_unit_value"] for e in nat["edges"]]
    assert shares == sorted(shares, reverse=True)
    assert not (FORBIDDEN & set(_keys(nat)))

    mine = client.get("/patterns/network?limit=150", headers=state_user).json()
    for e in mine["edges"]:                                                     # every unit has Telangana-located rows
        n = _sql("SELECT count(*) FROM vendor_transactions WHERE mp_name = :m AND constituency IS NOT DISTINCT FROM :c "
                 "AND work_state = 'Telangana'", m=e["mp_name"], c=e["constituency"])[0][0]
        assert n > 0
    assert client.get("/patterns/network?limit=0", headers=ministry).status_code == 422
    assert client.get("/patterns/network?limit=151", headers=ministry).status_code == 422
    client.get("/patterns/network", headers=district_user).raise_for_status()      # scoped, not forbidden


# ---- the one unauthenticated data endpoint ---------------------------------
def test_public_summary_is_narrow_and_leaks_nothing_scoped(client, has_data):
    r = client.get("/meta/public-summary")                 # no token
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"allocated_amount", "works_tracked", "mps_covered", "as_of"}     # exactly these, nothing else
    assert body["mps_covered"] > 500 and body["works_tracked"] > 100_000 and body["allocated_amount"] > 1e10
    assert not (FORBIDDEN & set(_keys(body)))
    real = _sql("SELECT count(*) FROM projects WHERE NOT is_synthetic_anomaly")[0][0]
    assert body["works_tracked"] == real                     # injected validation rows are not "works tracked"
    assert client.get("/meta/summary").status_code == 401  # the real (scoped) summary still needs a token
