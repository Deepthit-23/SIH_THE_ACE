"""District scoping is a (state, district) PAIR, never the district name alone.

District names repeat across states (Bilaspur in Himachal Pradesh and Chhattisgarh, Hamirpur in HP and UP,
Pratapgarh in Rajasthan and UP), and the source's `state` is the MP's state while `district` is where the work
is done. These tests use REAL same-named districts and try to break the wall: list, detail, search, export,
aggregates, the state map and the contractor network.
"""

import uuid

import pandas as pd
import pytest
from sqlalchemy import text

from app.auth import hash_password
from app.database import SessionLocal, engine
from app.models import User
from app.pipeline import location as L

PW = "DistrictTest!2026"
PAIRS = [("Himachal Pradesh", "BILASPUR"), ("Chhattisgarh", "BILASPUR"),
         ("Himachal Pradesh", "HAMIRPUR"), ("Uttar Pradesh", "HAMIRPUR"),
         ("Rajasthan", "PRATAPGARH"), ("Uttar Pradesh", "PRATAPGARH")]


def _sql(q, **p):
    with engine.begin() as c:
        res = c.execute(text(q), p)
        return res.all() if res.returns_rows else []


def _located(state, district):
    """ground truth straight from the table: projects LOCATED in (state, district)"""
    return _sql("SELECT id, state FROM projects WHERE lower(district)=lower(:d) "
                "AND lower(work_state)=lower(:s)", d=district, s=state)


@pytest.fixture(scope="module")
def make_district_user(client):
    """Insert district accounts straight into the DB (not via the admin API, so no audit noise)."""
    made = []

    def make(scope_value, scope_state):
        name = "pytest_dist_" + uuid.uuid4().hex[:8]
        with SessionLocal() as db:
            db.add(User(username=name, password_hash=hash_password(PW), role="district_authority",
                        scope_value=scope_value, scope_state=scope_state, is_active=True,
                        must_change_password=False))
            db.commit()
        made.append(name)
        r = client.post("/auth/login", json={"username": name, "password": PW})
        assert r.status_code == 200, r.text
        return {"Authorization": "Bearer " + r.json()["access_token"]}

    yield make
    _sql("DELETE FROM users WHERE username LIKE 'pytest\\_dist\\_%'")


@pytest.fixture(scope="module", autouse=True)
def _need_data():
    if not _sql("SELECT 1 FROM projects LIMIT 1") or not _sql("SELECT 1 FROM projects WHERE work_state IS NOT NULL LIMIT 1"):
        pytest.skip("no data / work_state not derived")


def _ids(client, hdr):
    out, offset = [], 0
    while True:
        r = client.get("/risk-scores", params={"limit": 200, "offset": offset}, headers=hdr).json()
        out += [i["id"] for i in r["items"]]
        offset += 200
        if offset >= r["total"]:
            return out


# ---- same-named districts are separate scopes -----------------------------------------------------
@pytest.mark.parametrize("a,b", [(PAIRS[0], PAIRS[1]), (PAIRS[2], PAIRS[3]), (PAIRS[4], PAIRS[5])])
def test_same_named_districts_in_different_states_never_see_each_other(client, make_district_user, a, b):
    ha, hb = make_district_user(a[1], a[0]), make_district_user(b[1], b[0])
    ids_a, ids_b = set(_ids(client, ha)), set(_ids(client, hb))
    assert ids_a == {r[0] for r in _located(*a)} and ids_b == {r[0] for r in _located(*b)}
    assert ids_a and ids_b and not (ids_a & ids_b)                       # two real, disjoint scopes
    # opening the other district's project by id is forbidden; a wrong-state district-name filter yields nothing
    other = next(iter(ids_b))
    assert client.get(f"/projects/{other}", headers=ha).status_code == 403
    assert client.get(f"/projects/{other}/case", headers=ha).status_code == 403
    nothing = client.get("/risk-scores", params={"district": b[1], "state": b[0], "limit": 200}, headers=ha).json()
    assert set(i["id"] for i in nothing["items"]) <= ids_a               # filters can narrow, never widen


def test_district_search_and_export_stay_inside_the_pair(client, make_district_user):
    hdr = make_district_user("BILASPUR", "Himachal Pradesh")
    mine = {r[0] for r in _located("Himachal Pradesh", "BILASPUR")}
    hits = client.get("/risk-scores", params={"q": "road", "limit": 200}, headers=hdr).json()["items"]
    assert {i["id"] for i in hits} <= mine
    csv = client.get("/risk-scores/export.csv", headers=hdr)
    assert csv.status_code == 200
    body = csv.text
    assert "Chhattisgarh" not in body.replace("Himachal Pradesh", "")     # no other state's rows in the export


def test_demo_hyderabad_authority_sees_exactly_the_works_located_in_hyderabad_telangana(client, district_user):
    truth = {r[0] for r in _located("Telangana", "HYDERABAD")}
    assert set(_ids(client, district_user)) == truth
    assert len(truth) >= 100
    # the 12 works of a Rajya Sabha member elected from UP are physically in Hyderabad: legitimately visible
    up_labelled = {r[0] for r in _sql("SELECT id FROM projects WHERE lower(district)='hyderabad' AND state='Uttar Pradesh'")}
    assert up_labelled and up_labelled <= truth
    assert client.get("/auth/me", headers=district_user).json()["scope_label"] == "HYDERABAD, Telangana"


def test_a_district_with_no_state_fails_closed(client, make_district_user):
    hdr = make_district_user("HYDERABAD", None)
    assert client.get("/risk-scores?limit=5", headers=hdr).json()["total"] == 0
    pid = _sql("SELECT id FROM projects WHERE district='HYDERABAD' LIMIT 1")[0][0]
    assert client.get(f"/projects/{pid}", headers=hdr).status_code == 403
    assert client.get("/patterns/states", headers=hdr).json()["items"] == []
    assert client.get("/patterns/network", headers=hdr).json()["edges"] == []


# ---- the two views where the leak used to show ------------------------------------------------------
def test_state_map_for_a_district_user_lands_only_on_the_districts_state(client, district_user, make_district_user):
    m = client.get("/patterns/states", headers=district_user).json()
    assert [i["state"] for i in m["items"]] == ["Telangana"]              # was: Telangana AND Uttar Pradesh (12)
    assert m["items"][0]["project_count"] == len(_located("Telangana", "HYDERABAD"))
    for scope in (("Himachal Pradesh", "BILASPUR"), ("Chhattisgarh", "BILASPUR")):
        hdr = make_district_user(scope[1], scope[0])
        items = client.get("/patterns/states", headers=hdr).json()["items"]
        assert [i["state"] for i in items] == [scope[0]]
        assert items[0]["project_count"] == len(_located(*scope))


def test_contractor_network_edges_stay_inside_the_district_pair(client, make_district_user):
    for scope in PAIRS:
        hdr = make_district_user(scope[1], scope[0])
        edges = client.get("/patterns/network?limit=150", headers=hdr).json()["edges"]
        for e in edges:                                                     # every unit touches this pair
            n = _sql("SELECT count(*) FROM vendor_transactions WHERE mp_name=:m AND constituency IS NOT DISTINCT FROM :c "
                     "AND lower(district)=lower(:d) AND lower(work_state)=lower(:s)",
                     m=e["mp_name"], c=e["constituency"], d=scope[1], s=scope[0])[0][0]
            assert n > 0, (scope, e)


def test_district_ranking_does_not_merge_same_named_districts(client, ministry):
    items = client.get("/patterns/districts", params={"limit": 100}, headers=ministry).json()["items"]
    assert len({(i["key"], i["state"]) for i in items}) == len(items)       # one row per (district, state)
    for i in [x for x in items if x["key"] != "(unknown)"][:25]:            # counts are the PAIR's, not the name's
        assert i["project_count"] == len(_located(i["state"], i["key"])), i
    detail = client.get("/districts/BILASPUR/pattern", params={"state": "Himachal Pradesh"}, headers=ministry).json()
    assert detail["project_count"] == len(_located("Himachal Pradesh", "BILASPUR")) and detail["state"] == "Himachal Pradesh"
    both = client.get("/districts/BILASPUR/pattern", headers=ministry).json()   # no state: legacy name-only aggregate
    assert both["project_count"] > detail["project_count"]


# ---- admin: creating a district user takes the pair --------------------------------------------------
def test_admin_creates_district_users_from_the_pair(client, ministry):
    def create(scope, state, name=None):
        return client.post("/admin/users", headers=ministry, json={
            "username": name or "pytest_dist_" + uuid.uuid4().hex[:8], "role": "district_authority",
            "scope_value": scope, "scope_state": state, "temp_password": PW})
    try:
        assert create("BILASPUR", None).status_code == 422                   # the state is mandatory
        assert create("BILASPUR", "Kerala").status_code == 422               # a pair that doesn't exist in the data
        ok = create("bilaspur", "himachal pradesh")
        assert ok.status_code == 201, ok.text
        body = ok.json()
        assert (body["scope_value"], body["scope_state"]) == ("BILASPUR", "Himachal Pradesh")
        assert body["scope_label"] == "BILASPUR, Himachal Pradesh"
        # a different state's account with the same district name is a different scope
        assert create("BILASPUR", "Chhattisgarh").json()["scope_state"] == "Chhattisgarh"
        # scope_state on any other role is rejected
        bad = client.post("/admin/users", headers=ministry, json={
            "username": "pytest_dist_" + uuid.uuid4().hex[:8], "role": "state_nodal", "scope_value": "Karnataka",
            "scope_state": "Karnataka", "temp_password": PW})
        assert bad.status_code == 422
        opts = client.get("/admin/scope-options?kind=district", headers=ministry).json()
        bil = {(o["state"], o["value"]) for o in opts if o["value"] == "BILASPUR"}
        assert {("Himachal Pradesh", "BILASPUR"), ("Chhattisgarh", "BILASPUR")} <= bil
        assert len(opts) == len({(o["state"], o["value"]) for o in opts})     # one entry per pair
    finally:
        _sql("DELETE FROM users WHERE username LIKE 'pytest\\_dist\\_%'")


# ---- derivation rule (pure) -------------------------------------------------------------------------
def _pairs(rows):
    return pd.DataFrame(rows, columns=["state", "district", "house", "rows"])


REF = {(L._state_key("Telangana"), L._n("Hyderabad")), (L._state_key("Himachal Pradesh"), L._n("Bilaspur")),
       (L._state_key("Chhattisgarh"), L._n("Bilaspur")), (L._state_key("Uttar Pradesh"), L._n("Agra"))}


def _map(rows):
    m = L.build_mapping(_pairs(rows), REF)
    return {(r.state, r.district): (r.work_state, r.method) for r in m.itertuples()}


def test_rule_relocates_a_cross_state_work_to_the_districts_real_state():
    m = _map([("Telangana", "HYDERABAD", "Lok Sabha", 100), ("Uttar Pradesh", "HYDERABAD", "Rajya Sabha", 12)])
    assert m[("Telangana", "HYDERABAD")] == ("Telangana", "home")
    assert m[("Uttar Pradesh", "HYDERABAD")] == ("Telangana", "cross_state")


def test_rule_keeps_genuine_same_name_districts_in_their_own_states():
    m = _map([("Himachal Pradesh", "BILASPUR", "Lok Sabha", 21), ("Chhattisgarh", "BILASPUR", "Lok Sabha", 77)])
    assert m[("Himachal Pradesh", "BILASPUR")] == ("Himachal Pradesh", "home")     # small but real: not a phantom
    assert m[("Chhattisgarh", "BILASPUR")] == ("Chhattisgarh", "home")


def test_rule_never_guesses_when_the_name_is_ambiguous():
    m = _map([("Himachal Pradesh", "BILASPUR", "Lok Sabha", 21), ("Chhattisgarh", "BILASPUR", "Lok Sabha", 77),
              ("Madhya Pradesh", "BILASPUR", "Rajya Sabha", 7)])
    assert m[("Madhya Pradesh", "BILASPUR")] == (None, "unresolved")      # two candidate homes: fails closed


def test_rule_places_a_small_new_district_whose_name_exists_in_only_one_state():
    m = _map([("Sikkim", "NAMCHI", "Rajya Sabha", 9)])
    assert m[("Sikkim", "NAMCHI")] == ("Sikkim", "only_state")            # not ambiguous: nothing else has this name


def test_rule_rejects_a_phantom_pair_that_only_a_few_out_of_state_works_create():
    m = _map([("Uttar Pradesh", "AGRA", "Lok Sabha", 188), ("Uttarakhand", "AGRA", "Lok Sabha", 38)])
    assert m[("Uttarakhand", "AGRA")] == ("Uttar Pradesh", "cross_state")


def test_rule_recognises_districts_created_after_the_2011_reference():
    m = _map([("Karnataka", "BENGALURU URBAN", "Lok Sabha", 640), ("Punjab", "BENGALURU URBAN", "Lok Sabha", 1)])
    assert m[("Karnataka", "BENGALURU URBAN")] == ("Karnataka", "home")
    assert m[("Punjab", "BENGALURU URBAN")] == ("Karnataka", "cross_state")
