"""Case-management workflow tests (run against the live DB, rolled back)."""

import pytest
from sqlalchemy import delete, select, text

from app.database import engine
from app.models import CaseReview
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


@pytest.fixture
def a_project_id() -> int:
    with engine.connect() as c:
        pid = c.execute(text("SELECT id FROM projects ORDER BY id LIMIT 1")).scalar()
    if pid is None:
        pytest.skip("no projects loaded")
    return pid


@pytest.fixture(autouse=True)
def _cleanup_case(a_project_id):
    yield
    with engine.begin() as c:
        c.execute(delete(CaseReview).where(CaseReview.project_id == a_project_id))
        c.execute(
            text("DELETE FROM audit_log WHERE event_type = 'case_review' AND project_id = :p"),
            {"p": a_project_id},
        )


def test_default_case_is_pending(a_project_id):
    r = client.get(f"/projects/{a_project_id}/case")
    assert r.status_code == 200
    assert r.json()["status"] == "pending"


def test_set_and_read_back(a_project_id):
    r = client.put(f"/projects/{a_project_id}/case", json={"status": "under_review", "reviewer": "auditor"})
    assert r.status_code == 200 and r.json()["status"] == "under_review"

    detail = client.get(f"/projects/{a_project_id}").json()
    assert detail["case_status"] == "under_review"


def test_dismiss_requires_a_note(a_project_id):
    bad = client.put(f"/projects/{a_project_id}/case", json={"status": "dismissed"})
    assert bad.status_code == 422

    ok = client.put(
        f"/projects/{a_project_id}/case",
        json={"status": "dismissed", "note": "legitimate cost variance, verified"},
    )
    assert ok.status_code == 200 and ok.json()["note"].startswith("legitimate")


def test_bad_status_rejected(a_project_id):
    assert client.put(f"/projects/{a_project_id}/case", json={"status": "wat"}).status_code == 422


def test_history_is_chained_into_audit_log(a_project_id):
    client.put(f"/projects/{a_project_id}/case", json={"status": "under_review"})
    client.put(f"/projects/{a_project_id}/case", json={"status": "confirmed"})

    hist = client.get(f"/projects/{a_project_id}/case/history").json()
    assert [h["status"] for h in hist] == ["under_review", "confirmed"]

    # the chain still verifies after the case events were appended
    v = client.get("/audit/verify").json()
    assert v["valid"] is True


def test_cases_list_and_filter(a_project_id):
    client.put(
        f"/projects/{a_project_id}/case",
        json={"status": "dismissed", "note": "false positive"},
    )
    listing = client.get("/cases", params={"status": "dismissed"}).json()
    assert any(i["project_id"] == a_project_id for i in listing["items"])
