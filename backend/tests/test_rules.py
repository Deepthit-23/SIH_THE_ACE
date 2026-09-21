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
# Rule 1b — official allocation ceiling
# --------------------------------------------------------------------------- #
def test_allocation_ceiling_skips_mp_with_missing_official_ceiling():
    """The single source row with no published ceiling is non-applicable, not ₹0."""
    proj = _projects([{"mp_name": "CHAVAN VASANTRAO BALWANTRAO", "final_amount": 9_999_999}])
    allocation = pd.DataFrame([{
        "mp_name": "CHAVAN VASANTRAO BALWANTRAO", "state": "Maharashtra",
        "official_allocated_ceiling": None,
    }])
    res = rules.allocation_ceiling_breach(proj, allocation)
    assert not res.loc[1, "flagged"]
    assert pd.isna(res.loc[1, "official_ceiling"])
    assert res.loc[1, "reason"] is None


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


# --------------------------------------------------------------------------- #
# allocation_ceiling_breach — more cases
# --------------------------------------------------------------------------- #
_ALLOC = pd.DataFrame([{
    "mp_name": "ABHISHEK MANU SINGHVI", "state": "Telangana",
    "official_allocated_ceiling": 10_000_000, "term_start": None,
}])


def _mp_rows(amounts, name="Dr. Abhishek Manu Singhvi (2026-32)"):
    return _projects([{"mp_name": name, "state": "Telangana", "final_amount": a} for a in amounts])


def _dated(amounts, name="Dr. Abhishek Manu Singhvi (2026-32)"):
    """Projects with strictly increasing completion dates, in list order."""
    rows = [{"mp_name": name, "state": "Telangana", "final_amount": a,
             "completion_date": SNAPSHOT_DATE - timedelta(days=1000 - 10 * i)} for i, a in enumerate(amounts)]
    return _projects(rows)


def test_ceiling_flags_only_the_project_that_crosses_the_line():
    # 4M + 4M = 8M (within), +3M -> 11M crosses the 10M ceiling. Only the third is flagged.
    res = rules.allocation_ceiling_breach(_dated([4_000_000, 4_000_000, 3_000_000]), _ALLOC)
    assert res["flagged"].tolist() == [False, False, True]     # name normalised: honorific + suffix
    assert "over their official allocation ceiling" in res.iloc[2]["reason"]
    assert res["excess_pct"].round(1).eq(10.0).all()           # MP-level figure is unchanged


def test_ceiling_later_projects_after_the_crossing_are_also_flagged():
    res = rules.allocation_ceiling_breach(_dated([9_000_000, 2_000_000, 1_000_000]), _ALLOC)
    assert res["flagged"].tolist() == [False, True, True]


def test_ceiling_order_follows_dates_not_row_order():
    rows = _dated([3_000_000, 4_000_000, 4_000_000])           # dates ascend with row order...
    rows.loc[rows.index[0], "completion_date"] = SNAPSHOT_DATE  # ...but the 3M project is now the latest
    res = rules.allocation_ceiling_breach(rows, _ALLOC)
    assert res["flagged"].tolist() == [True, False, False]


def test_ceiling_not_flagged_within_tolerance_or_below():
    assert not rules.allocation_ceiling_breach(_mp_rows([10_100_000]), _ALLOC)["flagged"].any()
    assert not rules.allocation_ceiling_breach(_mp_rows([5_000_000]), _ALLOC)["flagged"].any()


def test_ceiling_excludes_fixture_rows_from_total():
    proj = _mp_rows([6_000_000, 5_000_000])
    res = rules.allocation_ceiling_breach(proj, _ALLOC, exclude_from_total=[False, True])
    assert not res["flagged"].any()                   # 6M of 10M once the fixture is left out
    assert res["ceiling_utilization"].round(2).eq(0.6).all()


def test_ceiling_unmatched_mp_is_not_applicable():
    res = rules.allocation_ceiling_breach(_mp_rows([99_000_000], name="Somebody Else"), _ALLOC)
    assert not res["flagged"].any() and res["official_ceiling"].isna().all()


# --------------------------------------------------------------------------- #
# duplicate_work
# --------------------------------------------------------------------------- #
def _dup(rows):
    d0 = SNAPSHOT_DATE - timedelta(days=400)
    out = []
    for i, r in enumerate(rows):
        out.append({"mp_name": "MP D", "constituency": "C1", "external_id": str(1000 + i),
                    "completion_date": d0, "final_amount": 500_000, **r})
    return _projects(out)


DESC = "Rajiv Gandhi Balika Vidyalaya Kotwali Sirsa compound"


def test_duplicate_flags_same_work_at_similar_amount_on_different_dates():
    d1 = SNAPSHOT_DATE - timedelta(days=100)
    res = rules.duplicate_work(_dup([
        {"work_description": DESC},
        {"work_description": DESC + " ", "final_amount": 540_000, "completion_date": d1},
    ]))
    assert res["flagged"].all()
    assert "similarity" in res.iloc[0]["reason"]


def test_duplicate_requires_amount_agreement():
    d1 = SNAPSHOT_DATE - timedelta(days=100)
    res = rules.duplicate_work(_dup([
        {"work_description": DESC},
        {"work_description": DESC, "final_amount": 900_000, "completion_date": d1},
    ]))
    assert not res["flagged"].any()


def test_duplicate_same_day_batch_entries_not_flagged():
    res = rules.duplicate_work(_dup([{"work_description": DESC}, {"work_description": DESC}]))
    assert not res["flagged"].any()                   # multi-unit purchase, dates equal


def test_duplicate_same_work_id_is_lifecycle_not_duplicate():
    d1 = SNAPSHOT_DATE - timedelta(days=100)
    res = rules.duplicate_work(_dup([
        {"work_description": DESC, "external_id": "77"},
        {"work_description": DESC, "external_id": "77", "completion_date": d1},
    ]))
    assert not res["flagged"].any()


def test_duplicate_boilerplate_only_text_cannot_match():
    d1 = SNAPSHOT_DATE - timedelta(days=100)
    res = rules.duplicate_work(_dup([
        {"work_description": "Installation of the works"},
        {"work_description": "Installation of works", "completion_date": d1},
    ]))
    assert not res["flagged"].any()


def test_duplicate_different_serial_ranges_are_distinct_works():
    d1 = SNAPSHOT_DATE - timedelta(days=100)
    res = rules.duplicate_work(_dup([
        {"work_description": "Anganwadi kitchen sets Sl. No. 1-150 Kotwali Sirsa"},
        {"work_description": "Anganwadi kitchen sets Sl. No. 151-300 Kotwali Sirsa", "completion_date": d1},
    ]))
    assert not res["flagged"].any()


def test_duplicate_is_scoped_to_one_mp_and_constituency():
    d1 = SNAPSHOT_DATE - timedelta(days=100)
    res = rules.duplicate_work(_dup([
        {"work_description": DESC},
        {"work_description": DESC, "mp_name": "MP OTHER", "completion_date": d1},
    ]))
    assert not res["flagged"].any()


# --------------------------------------------------------------------------- #
# stalled — new-term dampening via the shared matcher
# --------------------------------------------------------------------------- #
def test_stalled_suppressed_for_mp_in_office_under_18_months():
    old = SNAPSHOT_DATE - timedelta(days=600)
    proj = _projects([{"status": "recommended", "recommendation_date": old,
                       "work_description": "Unique ghost road at Nowhere",
                       "mp_name": "Dr. New Member Rao (2026-32)", "state": "Telangana"}])
    vtx = _vtx([{"mp_name": "Someone Else", "work_description": "road"}])
    start = SNAPSHOT_DATE.year                          # term began this year -> < 18 months
    alloc = pd.DataFrame([{"mp_name": "NEW MEMBER RAO", "state": "Telangana",
                           "official_allocated_ceiling": 1, "term_start": start}])
    assert not rules.stalled_project(proj, vtx, mp_allocation=alloc).loc[1, "flagged"]
    assert rules.stalled_project(proj, vtx).loc[1, "flagged"]     # no allocation info -> flagged


def test_duplicate_records_the_matched_counterpart_and_similarity():
    d1 = SNAPSHOT_DATE - timedelta(days=100)
    proj = _dup([
        {"work_description": DESC, "external_id": "A"},
        {"work_description": DESC + " ", "final_amount": 540_000, "completion_date": d1, "external_id": "B"},
        {"work_description": "Completely unrelated street light Pipli Ward Nine", "external_id": "C"},
    ])
    res = rules.duplicate_work(proj)
    assert res.loc[1, "partner_id"] == 2 and res.loc[2, "partner_id"] == 1     # they point at each other
    assert res.loc[1, "similarity"] >= rules.DUPLICATE_TEXT_SIMILARITY
    assert res.loc[3, "partner_id"] == -1 and res.loc[3, "similarity"] == 0    # unflagged: no counterpart
