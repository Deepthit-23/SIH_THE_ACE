"""State scope is where the work is LOCATED (work_state), so the hierarchy nests:

    Ministry (national) > State (work_state) > District (work_state + district) > MP (mp_name, by name)

and works with no positive location evidence (work_state NULL: an ambiguous district name, or no district
recorded at all) FAIL CLOSED: no State or District scope can see
them; only the Ministry, and the MP who owns them, can. They still count in national totals and are reported.
"""

import uuid

import pytest
from sqlalchemy import text

from app.auth import hash_password
from app.database import SessionLocal, engine
from app.models import User
from app.pipeline import location as L

PW = "StateScope!2026"


def _sql(q, **p):
    with engine.begin() as c:
        res = c.execute(text(q), p)
        return res.all() if res.returns_rows else []


@pytest.fixture(scope="module", autouse=True)
def _need_derived():
    if not _sql("SELECT 1 FROM projects WHERE location_method IS NOT NULL LIMIT 1"):
        pytest.skip("work_state not derived")


@pytest.fixture(scope="module")
def make_user(client):
    def make(role, scope_value, scope_state=None):
        name = "pytest_scope_" + uuid.uuid4().hex[:8]
        with SessionLocal() as db:
            db.add(User(username=name, password_hash=hash_password(PW), role=role, scope_value=scope_value,
                        scope_state=scope_state, is_active=True, must_change_password=False))
            db.commit()
        r = client.post("/auth/login", json={"username": name, "password": PW})
        assert r.status_code == 200, r.text
        return {"Authorization": "Bearer " + r.json()["access_token"]}

    yield make
    _sql("DELETE FROM users WHERE username LIKE 'pytest\\_scope\\_%'")


def _ids(client, hdr):
    out, offset = [], 0
    while True:
        r = client.get("/risk-scores", params={"limit": 200, "offset": offset}, headers=hdr).json()
        out += [i["id"] for i in r["items"]]
        offset += 200
        if offset >= r["total"]:
            return out


UNRESOLVED = "SELECT id, state, district, mp_name FROM projects WHERE location_method = 'unresolved' ORDER BY id"


# ---- State scope = where the work is located ---------------------------------------------------------
def test_state_scope_is_the_work_location_not_the_mps_state(client, state_user):
    truth = {r[0] for r in _sql("SELECT id FROM projects WHERE work_state = 'Telangana'")}
    assert set(_ids(client, state_user)) == truth
    # 12 works of a Rajya Sabha member elected from UP are in Hyderabad: visible to Telangana's officer now
    up_in_hyd = {r[0] for r in _sql("SELECT id FROM projects WHERE state = 'Uttar Pradesh' AND work_state = 'Telangana'")}
    assert len(up_in_hyd) >= 12 and up_in_hyd <= truth
    # ... and Telangana MPs' works that sit in Kaithal, Haryana are NOT (they belong to Haryana's officer)
    tel_in_haryana = {r[0] for r in _sql("SELECT id FROM projects WHERE state = 'Telangana' AND work_state = 'Haryana'")}
    assert tel_in_haryana and not (tel_in_haryana & truth)
    for pid in list(tel_in_haryana)[:2]:
        assert client.get(f"/projects/{pid}", headers=state_user).status_code == 403
    for pid in list(up_in_hyd)[:2]:
        assert client.get(f"/projects/{pid}", headers=state_user).status_code == 200


def test_the_state_map_and_filters_only_ever_show_the_users_own_state(client, state_user):
    assert [i["state"] for i in client.get("/patterns/states", headers=state_user).json()["items"]] == ["Telangana"]
    assert client.get("/meta/filters", headers=state_user).json()["states"] == ["Telangana"]


# ---- the hierarchy nests ---------------------------------------------------------------------------------
def test_district_scope_is_always_inside_its_state_scope(client, state_user, district_user, make_user):
    assert set(_ids(client, district_user)) <= set(_ids(client, state_user))          # Hyderabad inside Telangana
    for st, dist in [("Himachal Pradesh", "BILASPUR"), ("Chhattisgarh", "BILASPUR"),
                     ("Uttar Pradesh", "PRATAPGARH"), ("Rajasthan", "PRATAPGARH")]:
        d = set(_ids(client, make_user("district_authority", dist, st)))
        s = set(_ids(client, make_user("state_nodal", st)))
        assert d and d <= s, (st, dist)


def test_hierarchy_holds_for_every_state_district_pair_in_the_data():
    """No project is visible to a district scope without being visible to its state's scope: both are the same
    work_state column, so this is true by construction -- assert it against the data, not the code."""
    bad = _sql("SELECT count(*) FROM projects WHERE district IS NOT NULL AND work_state IS NULL "
               "AND location_method <> 'unresolved'")[0][0]
    assert bad == 0                                      # with a district, NULL only ever means 'unresolved'
    # ... and the converse: every row with a NULL location has a recorded reason, in both tables
    for t in ("projects", "vendor_transactions"):
        assert _sql(f"SELECT count(*) FROM {t} WHERE work_state IS NOT NULL AND location_method IN "
                    "('unresolved','no_district','unlocated')")[0][0] == 0
    assert _sql("SELECT count(*) FROM projects WHERE work_state IS NULL AND location_method NOT IN ('unresolved','no_district','unlocated')")[0][0] == 0


# ---- works with no positive location evidence fail closed ---------------------------------------------------
# Two sets, identical treatment: 'unresolved' (ambiguous multi-state district name) and 'no_district' (no district
# recorded at all). Every assertion below runs against BOTH.
KINDS = ["unresolved", "no_district"]


def _set(kind, limit=None):
    q = f"SELECT id, state, district, mp_name FROM projects WHERE location_method = '{kind}' ORDER BY id"
    return _sql(q + (f" LIMIT {limit}" if limit else ""))


def _sample(rows, n=6):
    """a spread of ids across the set (first, last and evenly between), not just the first few"""
    if len(rows) <= n:
        return rows
    step = (len(rows) - 1) / (n - 1)
    return [rows[round(i * step)] for i in range(n)]


@pytest.mark.parametrize("kind", KINDS)
def test_null_location_sets_have_a_null_work_state_and_a_recorded_reason(kind):
    rows = _set(kind)
    assert rows, kind
    assert _sql(f"SELECT count(*) FROM projects WHERE location_method = '{kind}' AND work_state IS NOT NULL")[0][0] == 0
    if kind == "unresolved":
        assert {r[2] for r in rows} <= {"BILASPUR", "PRATAPGARH", "HAMIRPUR"}          # genuinely multi-state names
    else:
        assert all(r[2] is None for r in rows)                                          # no district recorded at all
    # the same holds for vendor transactions
    assert _sql(f"SELECT count(*) FROM vendor_transactions WHERE location_method = '{kind}' AND work_state IS NOT NULL")[0][0] == 0


@pytest.mark.parametrize("kind", KINDS)
def test_null_location_works_are_invisible_to_every_state_and_district_scope(client, make_user, ministry, kind):
    rows = _set(kind)
    ids = [r[0] for r in rows]
    idset = set(ids)
    by_state = {}
    for r in rows:
        by_state[r[1]] = by_state.get(r[1], 0) + 1
    # every state that owns some of these works (by MP state), the most affected first, plus the demo state
    states = [s for s, _ in sorted(by_state.items(), key=lambda kv: -kv[1])][:8]
    if kind == "unresolved":
        states = sorted(set(states) | {"Himachal Pradesh", "Chhattisgarh", "Uttar Pradesh", "Rajasthan", "Bihar", "Madhya Pradesh"})
    states = sorted(set(states) | {"Telangana"})
    sample = [r[0] for r in _sample(rows)]
    for n, st in enumerate(states):
        hdr = make_user("state_nodal", st)
        # the scoped total equals the ground truth over NON-NULL work_state -> a NULL can never be included
        assert client.get("/risk-scores?limit=1", headers=hdr).json()["total"] == \
            _sql("SELECT count(*) FROM projects WHERE work_state = :s", s=st)[0][0], (kind, st)
        for pid in sample:
            assert client.get(f"/projects/{pid}", headers=hdr).status_code == 403, (kind, st, pid)
        assert client.get(f"/projects/{sample[0]}/case", headers=hdr).status_code == 403
        if n < 3:                                                                        # CSV export: parse, don't grep
            export = client.get("/risk-scores/export.csv", headers=hdr).text
            import csv, io
            exported = {int(row[0]) for row in list(csv.reader(io.StringIO(export)))[1:] if row}
            assert not (exported & idset), (kind, st)
    # district scopes: the demo authority plus every candidate (district, state) pair for the ambiguous set
    pairs = {("HYDERABAD", "Telangana")}
    if kind == "unresolved":
        pairs |= {(r[2], st) for r in rows for st in states}
    for d, st in sorted(pairs):
        hdr = make_user("district_authority", d, st)
        assert client.get("/risk-scores?limit=1", headers=hdr).json()["total"] == _sql(
            "SELECT count(*) FROM projects WHERE district = :d AND work_state = :s", d=d, s=st)[0][0], (kind, d, st)
    # the Ministry still sees them
    for pid in sample:
        assert client.get(f"/projects/{pid}", headers=ministry).status_code == 200


@pytest.mark.parametrize("kind", KINDS)
def test_the_owning_mp_still_sees_their_null_location_works_by_name(client, make_user, kind):
    row = _set(kind, limit=1)[0]
    total = _sql("SELECT count(*) FROM projects WHERE mp_name = :m", m=row[3])[0][0]
    hdr = make_user("mp_self", row[3])
    assert client.get("/risk-scores?limit=1", headers=hdr).json()["total"] == total     # includes the NULL-location ones
    assert client.get(f"/projects/{row[0]}", headers=hdr).status_code == 200


def test_national_totals_count_every_null_location_work_and_say_so(client, ministry, state_user):
    n_unres = _sql("SELECT count(*) FROM projects WHERE location_method = 'unresolved'")[0][0]
    n_nod = _sql("SELECT count(*) FROM projects WHERE location_method = 'no_district'")[0][0]
    assert n_unres > 0 and n_nod > 1000
    nat = client.get("/patterns/states", headers=ministry).json()
    assert nat["unlocated_count"] == n_unres + n_nod == _sql("SELECT count(*) FROM projects WHERE work_state IS NULL")[0][0]
    total = client.get("/risk-scores?limit=1", headers=ministry).json()["total"]
    assert sum(i["project_count"] for i in nat["items"]) + nat["unlocated_count"] == total     # nothing dropped silently
    assert client.get("/patterns/states", headers=state_user).json()["unlocated_count"] == 0    # a scope can't match NULL
    ms = client.get("/meta/summary", headers=ministry).json()
    assert ms["projects_scored"] == total                                                       # header total = list total


def test_small_new_districts_with_an_unambiguous_name_are_placed_not_hidden(client, make_user):
    rows = _sql("SELECT id, work_state FROM projects WHERE location_method = 'only_state' LIMIT 20")
    assert rows and all(r[1] for r in rows)
    ids, st = [r[0] for r in rows], rows[0][1]
    hdr = make_user("state_nodal", st)
    assert {r[0] for r in rows if r[1] == st} <= set(_ids(client, hdr))


def test_an_underived_database_fails_closed_and_the_startup_check_repairs_it(client, make_user):
    """If work_state had never been derived (a restored old dump), every State scope would fail closed;
    ensure_derived() detects that at startup and derives it. Here: derived already -> nothing to do."""
    assert L.ensure_derived(engine) is False
