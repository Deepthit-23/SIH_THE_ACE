"""Unit tests for the rule engine -- hand-built rows, no DB."""

from datetime import timedelta

import pandas as pd

from app.pipeline import SNAPSHOT_DATE, rules


# --------------------------------------------------------------------------- #
# Rule 1 — cost anomaly
# --------------------------------------------------------------------------- #
def _projects(rows: list[dict]) -> pd.DataFrame:
    base = dict(
        id=0, status="completed", state="TestState", district="TestDist",
        derived_category="road_paving", sanctioned_amount=None, final_amount=None,
        recommendation_date=None, work_description="x", mp_name="MP A",
    )
    return pd.DataFrame([{**base, **r, "id": i + 1} for i, r in enumerate(rows)])


def test_cost_anomaly_flags_extreme_high_outlier():
    rows = [{"final_amount": 100_000} for _ in range(15)]
    rows.append({"final_amount": 5_000_000})
    res = rules.cost_anomaly(_projects(rows))
    assert res.iloc[-1]["flagged"]
    assert "average for TestDist" in res.iloc[-1]["reason"]
    assert not res.iloc[:-1]["flagged"].any()


def test_cost_anomaly_needs_enough_peers():
    rows = [{"final_amount": 100_000}, {"final_amount": 100_000}, {"final_amount": 9_000_000}]
    res = rules.cost_anomaly(_projects(rows))
    assert not res["flagged"].any()  # group too small to judge


def test_cost_anomaly_ignores_cheap_projects():
    rows = [{"final_amount": 1_000_000} for _ in range(15)]
    rows.append({"final_amount": 1})
    res = rules.cost_anomaly(_projects(rows))
    assert not res["flagged"].any()


# --------------------------------------------------------------------------- #
# Rule 2 — contractor concentration
# --------------------------------------------------------------------------- #
_VTX_COLS = [
    "mp_name", "constituency", "state", "house", "work_description", "vendor",
    "amount", "payment_status", "is_synthetic_anomaly",
]


def _vtx(rows: list[dict]) -> pd.DataFrame:
    base = dict(
        mp_name="MP A", constituency="CityX", state="StateY", house="Lok Sabha",
        work_description="road", vendor="V", amount=100_000,
        payment_status="Payment Success", is_synthetic_anomaly=False,
    )
    if not rows:
        return pd.DataFrame({c: pd.Series(dtype="object") for c in _VTX_COLS})
    return pd.DataFrame([{**base, **r} for r in rows])


def test_contractor_concentration_flags_dominant_vendor():
    rows = [{"vendor": "BigCo"} for _ in range(15)] + [{"vendor": f"S{i}"} for i in range(5)]
    res = rules.contractor_concentration(_vtx(rows))
    big = res[res["vendor"] == "BigCo"].iloc[0]
    assert big["flagged"]
    assert "BigCo accounts for" in big["reason"] and "CityX" in big["reason"]
    assert not res[res["vendor"] != "BigCo"]["flagged"].any()


def test_contractor_concentration_ignores_small_units():
    rows = [{"vendor": "BigCo"} for _ in range(4)]
    res = rules.contractor_concentration(_vtx(rows))
    assert not res["flagged"].any()


def test_contractor_concentration_rajya_sabha_groups_by_state():
    rows = [
        {"vendor": "BigCo", "house": "Rajya Sabha", "constituency": "Sitting Rajya Sabha"}
        for _ in range(15)
    ] + [
        {"vendor": f"S{i}", "house": "Rajya Sabha", "constituency": "Sitting Rajya Sabha"}
        for i in range(5)
    ]
    res = rules.contractor_concentration(_vtx(rows))
    big = res[res["vendor"] == "BigCo"].iloc[0]
    assert big["flagged"] and big["unit"] == "StateY" and big["unit_type"] == "state"


# --------------------------------------------------------------------------- #
# Rule 3 — stalled / ghost project
# --------------------------------------------------------------------------- #
def test_stalled_flags_old_unmatched_recommended():
    old = SNAPSHOT_DATE - timedelta(days=600)
    proj = _projects([
        {"status": "recommended", "recommendation_date": old,
         "work_description": "Construction of unique ghost road at Nowhere",
         "mp_name": "MP Ghost"},
        {"status": "recommended", "recommendation_date": SNAPSHOT_DATE - timedelta(days=30),
         "work_description": "fresh road", "mp_name": "MP Ghost"},
    ])
    vtx = _vtx([{"mp_name": "Someone Else", "work_description": "road"}])
    res = rules.stalled_project(proj, vtx)
    assert res.loc[1, "flagged"]
    assert "months ago" in res.loc[1, "reason"]
    assert not res.loc[2, "flagged"]


def test_stalled_not_flagged_when_completed_match_exists():
    old = SNAPSHOT_DATE - timedelta(days=600)
    desc = "Construction of CC road from village A to village B"
    proj = _projects([
        {"status": "recommended", "recommendation_date": old,
         "work_description": desc, "mp_name": "MP Match"},
        {"status": "completed", "work_description": desc + " phase 1", "mp_name": "MP Match"},
    ])
    res = rules.stalled_project(proj, _vtx([]), use_fuzzy=True)
    assert not res.loc[1, "flagged"]


def test_stalled_simple_variant_uses_mp_presence():
    old = SNAPSHOT_DATE - timedelta(days=600)
    proj = _projects([
        {"status": "recommended", "recommendation_date": old, "mp_name": "MP Lonely",
         "work_description": "road"},
        {"status": "completed", "mp_name": "MP Active", "work_description": "road"},
    ])
    res = rules.stalled_project(proj, _vtx([]), use_fuzzy=False)
    assert res.loc[1, "flagged"]  # MP Lonely has no completed work / no vendor txn


# --------------------------------------------------------------------------- #
# Rule 4 — payment gap
# --------------------------------------------------------------------------- #
def test_payment_gap_flags_high_inprogress_share():
    rows = (
        [{"amount": 1_000_000, "payment_status": "Payment In-Progress"} for _ in range(8)]
        + [{"amount": 1_000_000, "payment_status": "Payment Success"} for _ in range(2)]
    )
    summ = pd.DataFrame([{"mp_name": "MP A", "constituency": "CityX", "utilization_pct": 100.0}])
    res = rules.payment_gap(_vtx(rows), summ)
    row = res.iloc[0]
    assert row["flagged"]
    assert "in-progress despite 100% overall utilization" in row["reason"]


def test_payment_gap_not_flagged_when_share_low():
    rows = (
        [{"payment_status": "Payment In-Progress"} for _ in range(1)]
        + [{"payment_status": "Payment Success"} for _ in range(9)]
    )
    summ = pd.DataFrame([{"mp_name": "MP A", "constituency": "CityX", "utilization_pct": 100.0}])
    res = rules.payment_gap(_vtx(rows), summ)
    assert not res.iloc[0]["flagged"]
