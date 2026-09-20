"""Shared fixtures: a TestClient plus real bearer tokens for each of the 4 roles.

Tokens come from the real /auth/login endpoint using the documented demo
accounts (seeded by the same `seed_demo_users` the app runs at startup), so the
auth path under test is the production one.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth import DEMO_USERS, seed_demo_users
from app.database import SessionLocal, engine
from app.main import app

ROLE_USERS = {role: (u, pw) for u, pw, role, _ in DEMO_USERS}


@pytest.fixture(scope="session")
def client() -> TestClient:
    with SessionLocal() as db:
        seed_demo_users(db)
    return TestClient(app)


def _login(client: TestClient, role: str) -> dict:
    username, password = ROLE_USERS[role]
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def ministry(client):
    return _login(client, "ministry")


@pytest.fixture(scope="session")
def state_user(client):
    return _login(client, "state_nodal")


@pytest.fixture(scope="session")
def district_user(client):
    return _login(client, "district_authority")


@pytest.fixture(scope="session")
def mp_user(client):
    return _login(client, "mp_self")


@pytest.fixture(scope="session")
def has_data(client, ministry) -> bool:
    r = client.get("/risk-scores", params={"limit": 1}, headers=ministry)
    return r.status_code == 200 and r.json()["total"] > 0


@pytest.fixture
def case_project(has_data):
    """A Telangana project with no case history, cleaned up afterwards.

    Cleanup removes only the tail audit entries this test appended, so the
    hash-chain stays valid.
    """
    if not has_data:
        pytest.skip("no data loaded")
    with engine.connect() as c:
        pid = c.execute(text(
            "SELECT p.id FROM projects p JOIN risk_flags rf ON rf.project_id = p.id "
            "WHERE p.state ILIKE 'Telangana' "
            "AND NOT EXISTS (SELECT 1 FROM case_reviews cr WHERE cr.project_id = p.id) "
            "ORDER BY rf.combined_risk_score DESC LIMIT 1"
        )).scalar()
    if pid is None:
        pytest.skip("no suitable Telangana project")
    yield pid
    with engine.begin() as c:
        c.execute(text("DELETE FROM case_reviews WHERE project_id = :p"), {"p": pid})
        c.execute(text("DELETE FROM audit_log WHERE event_type = 'case_review' AND project_id = :p"), {"p": pid})
