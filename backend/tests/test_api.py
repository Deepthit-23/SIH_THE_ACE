"""API integration tests -- run against the live DB (risk_flags must be populated).

The single most important assertion: `is_synthetic_anomaly` / `anomaly_type`
never appear in ANY response payload.
"""

import pytest

FORBIDDEN = {"is_synthetic_anomaly", "anomaly_type"}


def _keys(obj):
    """Yield every dict key appearing anywhere in a JSON structure."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


def _assert_clean(payload):
    assert FORBIDDEN.isdisjoint(set(_keys(payload)))


def test_health(client, ministry):
    assert client.get("/health").json()["status"] == "ok"


def test_audit_verify_shape(client, ministry):
    body = client.get("/audit/verify", headers=ministry).json()
    assert {"valid", "entries_checked", "broken_at", "cached"} <= set(body)
    assert isinstance(body["valid"], bool)


def test_audit_verify_second_call_is_cached(client, ministry):
    client.get("/audit/verify", headers=ministry)
    assert client.get("/audit/verify", headers=ministry).json()["cached"] is True


def test_national_summary_shape(client, ministry, has_data):
    if not has_data:
        pytest.skip("no data loaded")
    b = client.get("/meta/summary", headers=ministry).json()
    assert b["projects_scored"] > 0
    assert b["allocated_amount"] > 0
    _assert_clean(b)


def test_csv_export(client, ministry, has_data):
    if not has_data:
        pytest.skip("no data loaded")
    r = client.get("/risk-scores/export.csv", params={"min_score": 90}, headers=ministry)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("project_id,work_id,")
    assert len(lines) > 1
    assert "is_synthetic_anomaly" not in r.text and "anomaly_type" not in r.text


def test_risk_scores_search(client, ministry, has_data):
    if not has_data:
        pytest.skip("no data loaded")
    r = client.get("/risk-scores", params={"q": "street light", "limit": 5}, headers=ministry)
    assert r.status_code == 200
    for item in r.json()["items"]:
        _assert_clean(item)


def test_risk_scores_shape_and_sorting(client, ministry, has_data):
    if not has_data:
        pytest.skip("no data loaded")
    r = client.get("/risk-scores", params={"limit": 25}, headers=ministry)
    assert r.status_code == 200
    body = r.json()
    _assert_clean(body)
    scores = [i["combined_risk_score"] for i in body["items"]]
    assert scores == sorted(scores, reverse=True)
    for item in body["items"]:
        assert item["severity"] in {"high", "medium", "low", "none", "unscored"}
        assert len(item["top_reasons"]) <= 2


def test_risk_scores_min_score_filter(client, ministry, has_data):
    if not has_data:
        pytest.skip("no data loaded")
    r = client.get("/risk-scores", params={"min_score": 90, "limit": 50}, headers=ministry)
    assert all(i["combined_risk_score"] >= 90 for i in r.json()["items"])


def test_project_detail_has_full_explanation(client, ministry, has_data):
    if not has_data:
        pytest.skip("no data loaded")
    top_id = client.get("/risk-scores", params={"limit": 1}, headers=ministry).json()["items"][0]["id"]
    r = client.get(f"/projects/{top_id}", headers=ministry)
    assert r.status_code == 200
    body = r.json()
    _assert_clean(body)
    assert isinstance(body["explanation"], list) and body["explanation"]
    for e in body["explanation"]:
        assert set(e) == {"source", "code", "label", "weight", "message"}
        assert e["source"] in {"rule", "ml"}
        assert isinstance(e["message"], str) and e["message"]


def test_project_404(client, ministry):
    assert client.get("/projects/999999999", headers=ministry).status_code == 404


def test_pattern_rankings_clean(client, ministry, has_data):
    if not has_data:
        pytest.skip("no data loaded")
    for path in ("/patterns/districts", "/patterns/contractors"):
        r = client.get(path, params={"limit": 5}, headers=ministry)
        assert r.status_code == 200
        _assert_clean(r.json())
        assert r.json()["items"]


def test_district_and_contractor_pattern_clean(client, ministry, has_data):
    if not has_data:
        pytest.skip("no data loaded")
    district = client.get("/patterns/districts", params={"limit": 1}, headers=ministry).json()["items"][0]["key"]
    if district != "(unknown)":
        r = client.get(f"/districts/{district}/pattern", headers=ministry)
        assert r.status_code == 200
        _assert_clean(r.json())
        assert r.json()["categories"]

    vendor = client.get("/patterns/contractors", params={"limit": 1}, headers=ministry).json()["items"][0]["key"]
    r = client.get(f"/contractors/{vendor}/pattern", headers=ministry)
    assert r.status_code == 200
    _assert_clean(r.json())
    assert r.json()["units"]


def test_pattern_404s(client, ministry):
    assert client.get("/districts/NOWHERE_XYZ_123/pattern", headers=ministry).status_code == 404
    assert client.get("/contractors/NOSUCHVENDOR_XYZ_123/pattern", headers=ministry).status_code == 404
