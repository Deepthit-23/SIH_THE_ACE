"""Ministry-only user management: server-side role enforcement, credential handling, forced
first-login password change, deactivation, and audit-chain coverage.

Users created here are named pytest_* and deleted at the end of the module. Their audit entries
stay (the chain is append-only by design), which is itself part of what is being tested.
"""

import json
import uuid

import pytest
from sqlalchemy import text

from app.audit import EVENT_ADMIN_ACTION, verify_chain
from app.database import engine

PW = "TempPass!2026"
NEW_PW = "MyOwnPass!2026"


def _sql(q, **p):
    with engine.begin() as c:
        res = c.execute(text(q), p)
        return res.all() if res.returns_rows else []


def _uname() -> str:
    return "pytest_" + uuid.uuid4().hex[:8]


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _login(client, username, password):
    return client.post("/auth/login", json={"username": username, "password": password})


@pytest.fixture(scope="module", autouse=True)
def _cleanup_users(client):
    yield
    _sql("DELETE FROM users WHERE username LIKE 'pytest\\_%'")


def _create(client, ministry, role="state_nodal", scope="Karnataka", username=None, password=PW):
    body = {"username": username or _uname(), "role": role, "scope_value": scope, "temp_password": password}
    return client.post("/admin/users", json=body, headers=ministry)


# ---- server-side role enforcement ------------------------------------------------------------
@pytest.mark.parametrize("who", ["state_user", "district_user", "mp_user"])
def test_non_ministry_tokens_are_forbidden_on_every_admin_endpoint(client, request, ministry, who):
    tok = request.getfixturevalue(who)
    name = _uname()
    r = client.post("/admin/users", json={"username": name, "role": "state_nodal",
                                          "scope_value": "Karnataka", "temp_password": PW}, headers=tok)
    assert r.status_code == 403
    assert not _sql("SELECT 1 FROM users WHERE username = :u", u=name)          # nothing was created
    assert client.get("/admin/users", headers=tok).status_code == 403
    assert client.patch("/admin/users/1", json={"is_active": False}, headers=tok).status_code == 403
    assert client.get("/admin/scope-options?kind=state", headers=tok).status_code == 403


def test_state_token_cannot_create_a_ministry_or_any_other_user_by_direct_call(client, state_user):
    """The case called out explicitly: a State-role token calling the endpoint directly."""
    before = _sql("SELECT count(*) FROM users")[0][0]
    for role, scope in [("ministry", None), ("state_nodal", "Karnataka"), ("mp_self", "Alok Kumar Suman")]:
        r = client.post("/admin/users", json={"username": _uname(), "role": role, "scope_value": scope,
                                              "temp_password": PW}, headers=state_user)
        assert r.status_code == 403, (role, r.text)
    assert _sql("SELECT count(*) FROM users")[0][0] == before


def test_admin_endpoints_need_a_token(client):
    assert client.get("/admin/users").status_code == 401
    assert client.post("/admin/users", json={}).status_code == 401


# ---- create / list ---------------------------------------------------------------------------
def test_create_hashes_password_and_never_returns_it(client, ministry):
    r = _create(client, ministry)
    assert r.status_code == 201, r.text
    u = r.json()
    assert u["is_active"] and u["must_change_password"]
    assert u["scope_value"] == "Karnataka" and u["role"] == "state_nodal"
    assert not {"password", "password_hash", "temp_password"} & set(u)          # no credential fields
    assert PW not in json.dumps(u) and "$2" not in json.dumps(u)              # no plaintext, no hash
    stored = _sql("SELECT password_hash FROM users WHERE username = :u", u=u["username"])[0][0]
    assert stored.startswith("$2") and PW not in stored                       # bcrypt, not plaintext


def test_list_users_includes_demo_accounts_and_new_user(client, ministry):
    new = _create(client, ministry).json()["username"]
    rows = client.get("/admin/users", headers=ministry).json()
    names = {u["username"] for u in rows}
    assert {"ministry_demo", "state_demo", "district_demo", "mp_demo", new} <= names
    assert all("password_hash" not in u for u in rows)
    demo = next(u for u in rows if u["username"] == "state_demo")
    assert demo["is_active"] and not demo["must_change_password"]           # demo accounts untouched


def test_scope_is_validated_against_the_data_and_canonicalised(client, ministry):
    assert _create(client, ministry, scope="Atlantis").status_code == 422
    assert _create(client, ministry, scope=None).status_code == 422
    assert _create(client, ministry, role="ministry", scope="Karnataka").status_code == 422
    ok = _create(client, ministry, scope="karnataka")                          # any casing -> stored casing
    assert ok.status_code == 201 and ok.json()["scope_value"] == "Karnataka"
    assert _create(client, ministry, role="ministry", scope=None).status_code == 201


def test_bad_input_and_duplicates_are_rejected(client, ministry):
    name = _uname()
    assert _create(client, ministry, username=name).status_code == 201
    assert _create(client, ministry, username=name.upper()).status_code == 409   # case-insensitive
    assert _create(client, ministry, password="short").status_code == 422
    assert _create(client, ministry, role="superuser").status_code == 422
    assert _create(client, ministry, username="a b").status_code == 422


def test_scope_options_come_from_the_data(client, ministry):
    states = client.get("/admin/scope-options?kind=state", headers=ministry).json()
    assert any(s["value"] == "Karnataka" for s in states)
    assert client.get("/admin/scope-options?kind=district", headers=ministry).json()
    mp = client.get("/admin/scope-options?kind=mp&q=singhvi", headers=ministry).json()
    assert any("Singhvi" in m["value"] for m in mp)
    assert client.get("/admin/scope-options?kind=mp&q=%25", headers=ministry).json() == []   # '%' is not a wildcard


# ---- forced first-login password change ------------------------------------------------------
def test_new_user_must_change_password_before_anything_else(client, ministry):
    name = _uname()
    _create(client, ministry, username=name)
    r = _login(client, name, PW)
    assert r.status_code == 200 and r.json()["must_change_password"] is True
    h = _hdr(r.json()["access_token"])
    # blocked server-side (not just hidden in the UI) ...
    blocked = client.get("/risk-scores", headers=h)
    assert blocked.status_code == 403 and blocked.json()["detail"] == "password_change_required"
    assert client.get("/meta/summary", headers=h).status_code == 403
    assert client.get("/admin/users", headers=h).status_code == 403
    # ... except who-am-I and the change itself
    assert client.get("/auth/me", headers=h).json()["must_change_password"] is True
    assert client.post("/auth/change-password", headers=h,
                       json={"current_password": "wrong-password", "new_password": NEW_PW}).status_code == 400
    assert client.post("/auth/change-password", headers=h,
                       json={"current_password": PW, "new_password": PW}).status_code == 400
    assert client.post("/auth/change-password", headers=h,
                       json={"current_password": PW, "new_password": "short"}).status_code == 422
    assert client.post("/auth/change-password", headers=h,
                       json={"current_password": PW, "new_password": NEW_PW}).status_code == 200
    ok = client.get("/risk-scores?limit=200", headers=h)
    assert ok.status_code == 200 and ok.json()["total"] > 0
    assert {i["state"] for i in ok.json()["items"]} == {"Karnataka"}       # scope enforced for the new user
    assert _login(client, name, PW).status_code == 401                       # temp password is dead
    assert _login(client, name, NEW_PW).json()["must_change_password"] is False


# ---- deactivate / reactivate / reset ---------------------------------------------------------
def test_deactivation_kills_existing_tokens_and_blocks_login_until_reactivated(client, ministry):
    name = _uname()
    uid = _create(client, ministry, username=name).json()["id"]
    tok = _login(client, name, PW).json()["access_token"]
    client.post("/auth/change-password", headers=_hdr(tok), json={"current_password": PW, "new_password": NEW_PW})
    assert client.get("/risk-scores?limit=1", headers=_hdr(tok)).status_code == 200

    r = client.patch(f"/admin/users/{uid}", json={"is_active": False}, headers=ministry)
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert client.get("/risk-scores?limit=1", headers=_hdr(tok)).status_code == 401      # same token, now dead
    assert _login(client, name, "wrong").status_code == 401                               # no username probing
    assert _login(client, name, NEW_PW).status_code == 403

    assert client.patch(f"/admin/users/{uid}", json={"is_active": True}, headers=ministry).json()["is_active"]
    assert client.get("/risk-scores?limit=1", headers=_hdr(tok)).status_code == 200


def test_reset_password_forces_change_and_invalidates_the_old_password(client, ministry):
    name = _uname()
    uid = _create(client, ministry, username=name).json()["id"]
    r = client.patch(f"/admin/users/{uid}", json={"reset_password": "ResetPass!2026"}, headers=ministry)
    assert r.status_code == 200 and r.json()["must_change_password"] is True
    assert _login(client, name, PW).status_code == 401
    assert _login(client, name, "ResetPass!2026").status_code == 200


def test_guards_against_locking_the_ministry_out(client, ministry):
    me = next(u for u in client.get("/admin/users", headers=ministry).json() if u["username"] == "ministry_demo")
    assert client.patch(f"/admin/users/{me['id']}", json={"is_active": False}, headers=ministry).status_code == 400
    assert client.patch("/admin/users/99999999", json={"is_active": False}, headers=ministry).status_code == 404
    assert client.patch(f"/admin/users/{me['id']}", json={}, headers=ministry).status_code == 422


def test_demo_accounts_still_work(client):
    for u, p in [("ministry_demo", "DemoMinistry!2026"), ("state_demo", "DemoState!2026"),
                 ("district_demo", "DemoDistrict!2026"), ("mp_demo", "DemoMP!2026")]:
        r = _login(client, u, p)
        assert r.status_code == 200 and r.json()["must_change_password"] is False


# ---- audit chain -----------------------------------------------------------------------------
def test_every_admin_action_is_in_the_hash_chain_without_secrets(client, ministry):
    name = _uname()
    uid = _create(client, ministry, username=name).json()["id"]
    client.patch(f"/admin/users/{uid}", json={"is_active": False}, headers=ministry)
    client.patch(f"/admin/users/{uid}", json={"is_active": True}, headers=ministry)
    client.patch(f"/admin/users/{uid}", json={"reset_password": "AnotherPass!2026"}, headers=ministry)
    client.patch(f"/admin/users/{uid}", json={"is_active": True}, headers=ministry)         # no-op: no entry

    rows = _sql("SELECT event_type, payload, project_id FROM audit_log "
                "WHERE payload->>'target_username' = :u ORDER BY id", u=name)
    assert [r[1]["action"] for r in rows] == ["user_created", "user_deactivated", "user_reactivated", "password_reset"]
    assert {r[0] for r in rows} == {EVENT_ADMIN_ACTION} == {"admin_action"}
    assert all(r[1]["actor"] == "ministry:ministry_demo" and r[2] is None for r in rows)
    blob = json.dumps([r[1] for r in rows])
    for secret in (PW, "AnotherPass!2026", "$2b$", "$2a$", "password_hash"):
        assert secret not in blob
    with engine.connect() as conn:
        assert verify_chain(conn, use_cache=False)["valid"] is True


def test_tampering_with_an_admin_entry_breaks_the_chain(client, ministry):
    name = _uname()
    _create(client, ministry, username=name)
    with engine.connect() as conn:
        tx = conn.begin()                                            # never committed: real chain untouched
        conn.execute(text("UPDATE audit_log SET payload = jsonb_set(payload, '{actor}', '\"someone_else\"') "
                          "WHERE payload->>'target_username' = :u"), {"u": name})
        assert verify_chain(conn, use_cache=False)["valid"] is False
        tx.rollback()
    with engine.connect() as conn:
        assert verify_chain(conn, use_cache=False)["valid"] is True
