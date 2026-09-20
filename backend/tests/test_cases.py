"""Case-management workflow + who may do what (state/district/ministry/MP)."""

import pytest
from sqlalchemy import text

from app.database import engine


def _put(client, headers, pid, **body):
    return client.put(f"/projects/{pid}/case", json=body, headers=headers)


def test_default_case_is_pending(client, ministry, case_project):
    r = client.get(f"/projects/{case_project}/case", headers=ministry)
    assert r.status_code == 200 and r.json()["status"] == "pending"


def test_set_and_read_back(client, ministry, case_project):
    assert _put(client, ministry, case_project, status="under_review").json()["status"] == "under_review"
    detail = client.get(f"/projects/{case_project}", headers=ministry).json()
    assert detail["case_status"] == "under_review"


def test_dismiss_requires_a_note(client, ministry, case_project):
    assert _put(client, ministry, case_project, status="dismissed").status_code == 422
    assert _put(client, ministry, case_project, status="dismissed", note="  ").status_code == 422
    ok = _put(client, ministry, case_project, status="dismissed", note="legitimate cost variance")
    assert ok.status_code == 200 and ok.json()["note"].startswith("legitimate")


def test_bad_status_rejected(client, ministry, case_project):
    assert _put(client, ministry, case_project, status="wat").status_code == 422


def test_history_is_chained_into_audit_log(client, ministry, case_project):
    _put(client, ministry, case_project, status="under_review")
    _put(client, ministry, case_project, status="confirmed")
    hist = client.get(f"/projects/{case_project}/case/history", headers=ministry).json()
    assert [h["status"] for h in hist] == ["under_review", "confirmed"]
    assert client.get("/audit/verify", headers=ministry).json()["valid"] is True


def test_cases_list_and_filter(client, ministry, case_project):
    _put(client, ministry, case_project, status="dismissed", note="false positive")
    listing = client.get("/cases", params={"status": "dismissed"}, headers=ministry).json()
    assert any(i["project_id"] == case_project for i in listing["items"])


# ---- permissions ------------------------------------------------------------
def test_mp_cannot_write_and_nothing_is_persisted(client, mp_user, case_project):
    r = _put(client, mp_user, case_project, status="dismissed", note="trying to clear my own flag")
    assert r.status_code == 403
    with engine.connect() as c:
        n = c.execute(text("SELECT count(*) FROM case_reviews WHERE project_id = :p"),
                      {"p": case_project}).scalar()
        ev = c.execute(text("SELECT count(*) FROM audit_log WHERE event_type='case_review' AND project_id=:p"),
                       {"p": case_project}).scalar()
    assert n == 0 and ev == 0


def test_mp_rejected_even_for_a_project_in_their_own_portfolio(client, mp_user, ministry, has_data):
    mine = client.get("/risk-scores", params={"limit": 1}, headers=mp_user).json()
    if not mine["items"]:
        pytest.skip("MP demo account has no projects in this dataset")
    pid = mine["items"][0]["id"]
    assert _put(client, mp_user, pid, status="under_review").status_code == 403


def test_state_user_can_confirm_and_dismiss_in_scope(client, state_user, case_project):
    assert _put(client, state_user, case_project, status="confirmed").status_code == 200
    r = _put(client, state_user, case_project, status="dismissed", note="verified against tender documents")
    assert r.status_code == 200 and r.json()["status"] == "dismissed"


def test_district_user_can_confirm_within_their_district(client, district_user, ministry, has_data):
    mine = client.get("/risk-scores", params={"limit": 1}, headers=district_user).json()
    if not mine["items"]:
        pytest.skip("district demo account has no projects")
    pid = mine["items"][0]["id"]
    try:
        assert _put(client, district_user, pid, status="confirmed").status_code == 200
    finally:
        with engine.begin() as c:
            c.execute(text("DELETE FROM case_reviews WHERE project_id=:p"), {"p": pid})
            c.execute(text("DELETE FROM audit_log WHERE event_type='case_review' AND project_id=:p"), {"p": pid})


def test_state_user_cannot_act_outside_their_state(client, state_user, ministry, has_data):
    with engine.connect() as c:
        other = c.execute(text("SELECT id FROM projects WHERE state NOT ILIKE 'Telangana' LIMIT 1")).scalar()
    assert _put(client, state_user, other, status="under_review").status_code == 403
    assert client.get(f"/projects/{other}/case", headers=state_user).status_code == 403


def test_ministry_overrides_and_state_cannot_undo_a_ministry_decision(client, ministry, state_user, case_project):
    _put(client, state_user, case_project, status="dismissed", note="state says false positive")
    # ministry overrides the state decision
    o = _put(client, ministry, case_project, status="confirmed", note="ministry re-reviewed: genuine")
    assert o.status_code == 200 and o.json()["status"] == "confirmed"
    # ...and the state can no longer flip it back
    r = _put(client, state_user, case_project, status="dismissed", note="trying to reverse the ministry")
    assert r.status_code == 403
    assert client.get(f"/projects/{case_project}/case", headers=ministry).json()["status"] == "confirmed"


def test_reviewer_comes_from_the_token_not_the_request_body(client, state_user, case_project):
    r = _put(client, state_user, case_project, status="under_review", reviewer="ministry:someone_else")
    assert r.json()["reviewer"] == "state_nodal:state_demo"
