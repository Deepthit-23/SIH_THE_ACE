"""Unit tests for the risk combiner weighting + explanation assembly."""

import pandas as pd

from app.pipeline import risk_scorer


PROJECTS = pd.DataFrame([
    {"id": 1, "mp_name": "MP1", "constituency": "C1"},  # cost only
    {"id": 2, "mp_name": "MP2", "constituency": "C2"},  # stalled only
    {"id": 3, "mp_name": "MP3", "constituency": "C3"},  # contractor + cost
    {"id": 4, "mp_name": "MP4", "constituency": "C4"},  # ML only
    {"id": 5, "mp_name": "MP5", "constituency": "C5"},  # nothing
])


def _cost():
    return pd.DataFrame(
        {"flagged": [True, False, True, False, False],
         "reason": ["Cost is 5.0x the road paving average for C1", None,
                    "Cost is 4.0x the road paving average for C3", None, None],
         "amount_z": [4.0, 0.0, 3.0, 0.0, 0.0]},
        index=pd.Index([1, 2, 3, 4, 5], name="project_id"),
    )


def _stalled():
    return pd.DataFrame(
        {"flagged": [False, True, False, False, False],
         "reason": [None, "Recommended 20 months ago, no completion or payment activity recorded",
                    None, None, None]},
        index=pd.Index([1, 2, 3, 4, 5], name="project_id"),
    )


def _contractor():
    return pd.DataFrame([
        {"mp_name": "MP3", "vendor": "BigCo", "unit": "C3", "unit_type": "constituency",
         "flagged": True, "reason": "Vendor BigCo accounts for 70% of transaction value for MP3 in C3",
         "share_count": 0.5, "share_value": 0.7, "txn_count": 15, "unit_txn_count": 25},
    ])


def _payment():
    return pd.DataFrame(columns=["mp_name", "constituency", "flagged", "reason",
                                 "in_progress_share", "utilization_pct", "txn_count"])


def _ml():
    return pd.DataFrame(
        {"anomaly_score": [0.1, 0.1, 0.2, 0.5, 0.0],
         "ml_percentile": [50.0, 50.0, 50.0, 99.0, 20.0],
         "ml_flag": [False, False, False, True, False],
         "ml_reason": [None, None, None, "Anomaly model: cost is a large multiple of the typical amount", None]},
        index=pd.Index([1, 2, 3, 4, 5], name="project_id"),
    )


def _run():
    return risk_scorer.combine(PROJECTS, _cost(), _stalled(), _contractor(), _payment(), _ml())


def test_scores_in_range():
    out = _run()
    assert out["combined_risk_score"].between(0, 100).all()


def test_rule_scores_reflect_points():
    out = _run()
    assert out.loc[1, "rule_score"] == 40        # cost
    assert out.loc[2, "rule_score"] == 15        # stalled (weak)
    assert out.loc[3, "rule_score"] == 70        # cost 40 + contractor 30
    assert out.loc[5, "rule_score"] == 0


def test_stalled_only_below_cost_only():
    out = _run()
    assert out.loc[2, "combined_risk_score"] < out.loc[1, "combined_risk_score"]


def test_contractor_plus_cost_is_high():
    out = _run()
    assert out.loc[3, "combined_risk_score"] >= 70


def test_ml_only_surfaces_moderately():
    out = _run()
    assert 60 < out.loc[4, "combined_risk_score"] < 90
    assert out.loc[5, "combined_risk_score"] < 40


def test_cost_z_tiebreaker_discriminates_within_identical_flags():
    """Two projects, identical rule flags, different cost z -> different scores."""
    idx = pd.Index([10, 11], name="project_id")
    proj = pd.DataFrame([
        {"id": 10, "mp_name": "M", "constituency": "C"},
        {"id": 11, "mp_name": "M", "constituency": "C"},
    ])
    cost = pd.DataFrame(
        {"flagged": [True, True],
         "reason": ["Cost is 3x the road paving average for C", "Cost is 40x the road paving average for C"],
         "amount_z": [2.5, 30.0]},
        index=idx,
    )
    stalled = pd.DataFrame({"flagged": [False, False], "reason": [None, None]}, index=idx)
    contractor = pd.DataFrame(
        columns=["mp_name", "vendor", "unit", "flagged", "reason", "share_count", "share_value"]
    )
    payment = pd.DataFrame(columns=["mp_name", "constituency", "flagged", "reason"])
    ml = pd.DataFrame(
        {"anomaly_score": [0.1, 0.1], "ml_percentile": [96.0, 96.0],
         "ml_flag": [True, True], "ml_reason": ["m", "m"]},
        index=idx,
    )
    out = risk_scorer.combine(proj, cost, stalled, contractor, payment, ml)
    assert out.loc[11, "combined_risk_score"] > out.loc[10, "combined_risk_score"] + 4


def test_explanation_ordered_by_trust_then_ml_last():
    out = _run()
    p3 = out.loc[3, "explanation"]
    assert [e["code"] for e in p3] == ["cost_anomaly", "contractor_concentration"]
    p4 = out.loc[4, "explanation"]
    assert len(p4) == 1 and p4[0]["source"] == "ml"


def test_ml_fragments_suppressed_when_rule_covers_them():
    idx = pd.Index([20, 21], name="project_id")
    proj = pd.DataFrame([
        {"id": 20, "mp_name": "M", "constituency": "C"},   # cost rule fires
        {"id": 21, "mp_name": "M", "constituency": "C"},   # no rule fires
    ])
    cost = pd.DataFrame(
        {"flagged": [True, False],
         "reason": ["Cost is 6x the road paving average for C", None],
         "amount_z": [6.0, 6.0]},
        index=idx,
    )
    stalled = pd.DataFrame({"flagged": [False, False], "reason": [None, None]}, index=idx)
    contractor = pd.DataFrame(
        columns=["mp_name", "vendor", "unit", "flagged", "reason", "share_count", "share_value"]
    )
    payment = pd.DataFrame(columns=["mp_name", "constituency", "flagged", "reason"])
    ml = pd.DataFrame(
        {"anomaly_score": [0.2, 0.2], "ml_percentile": [97.0, 97.0], "ml_flag": [True, True]},
        index=idx,
    )
    # both projects' top ML fragment is the cost one
    frags = {
        20: [("amount_ratio_to_median", "the cost is many times the typical amount for similar projects"),
             ("mp_in_progress_share", "a large share of this MP's payments are stuck in-progress")],
        21: [("amount_ratio_to_median", "the cost is many times the typical amount for similar projects"),
             ("mp_in_progress_share", "a large share of this MP's payments are stuck in-progress")],
    }
    out = risk_scorer.combine(proj, cost, stalled, contractor, payment, ml, ml_fragments=frags)

    ml20 = [e for e in out.loc[20, "explanation"] if e["source"] == "ml"][0]["message"]
    ml21 = [e for e in out.loc[21, "explanation"] if e["source"] == "ml"][0]["message"]
    # 20: cost rule fired -> cost fragment dropped, payment fragment surfaces instead
    assert "many times the typical amount" not in ml20
    assert "payments are stuck in-progress" in ml20
    # 21: no rule fired -> cost fragment kept
    assert "many times the typical amount" in ml21


def test_rule_flags_dict_shape():
    out = _run()
    assert set(out.loc[1, "rule_flags"]) == {
        "cost_anomaly", "contractor_concentration", "payment_gap", "stalled_project"
    }
    assert out.loc[1, "rule_flags"]["stalled_project"] is False
    assert out.loc[2, "rule_flags"]["stalled_project"] is True
