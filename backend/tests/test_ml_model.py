"""Unit tests for the Isolation Forest detector + explainability."""

from datetime import timedelta

import pandas as pd

from app.pipeline import SNAPSHOT_DATE, ml_model


def _projects(n_normal: int = 30, extreme: bool = False) -> pd.DataFrame:
    rows = []
    for i in range(n_normal):
        rows.append(dict(
            id=i + 1, status="completed", state="StateA", district="DistA",
            derived_category="road_paving", sanctioned_amount=None,
            final_amount=500_000 + (i % 5) * 10_000, recommendation_date=None,
            completion_date=SNAPSHOT_DATE - timedelta(days=200), status_reason=None,
            work_description="cc road", mp_name=f"MP{i % 4}", constituency="C1",
            is_rajya_sabha=False, has_images=(i % 2 == 0), average_rating=None,
        ))
    if extreme:
        rows.append(dict(
            id=n_normal + 1, status="completed", state="StateA", district="DistA",
            derived_category="road_paving", sanctioned_amount=None,
            final_amount=80_000_000, recommendation_date=None,
            completion_date=SNAPSHOT_DATE - timedelta(days=5),
            work_description="cc road", mp_name="MP0", constituency="C1",
            is_rajya_sabha=False, has_images=False, average_rating=None,
        ))
    return pd.DataFrame(rows)


def _vtx() -> pd.DataFrame:
    return pd.DataFrame([
        dict(mp_name="MP0", constituency="C1", state="StateA", house="Lok Sabha",
             work_description="road", vendor="V1", amount=200_000,
             payment_status="Payment Success", is_synthetic_anomaly=False),
        dict(mp_name="MP1", constituency="C1", state="StateA", house="Lok Sabha",
             work_description="road", vendor="V2", amount=200_000,
             payment_status="Payment In-Progress", is_synthetic_anomaly=False),
    ])


def _mps() -> pd.DataFrame:
    return pd.DataFrame([
        dict(mp_name=f"MP{i}", constituency="C1", completion_rate_pct=40.0 + i)
        for i in range(4)
    ])


def test_feature_matrix_shape_and_no_label_leak():
    X = ml_model.build_feature_matrix(_projects(), _vtx(), _mps())
    assert list(X.columns) == ml_model.FEATURE_COLUMNS
    assert "is_synthetic_anomaly" not in X.columns
    assert "anomaly_type" not in X.columns
    assert "is_synthetic_anomaly" not in ml_model.FEATURE_COLUMNS
    assert X.index.name == "project_id"
    assert not X.isna().any().any()
    assert len(X) == 30


def test_train_and_score_ranges():
    X = ml_model.build_feature_matrix(_projects(), _vtx(), _mps())
    model = ml_model.train_isolation_forest(X, contamination=0.05)
    s = ml_model.score(model, X)
    assert set(s.columns) == {"anomaly_score", "ml_percentile", "ml_flag"}
    assert s["ml_percentile"].between(0, 100).all()
    assert s["ml_flag"].dtype == bool
    assert len(s) == len(X)


def test_extreme_row_scores_higher_and_is_explained():
    X = ml_model.build_feature_matrix(_projects(extreme=True), _vtx(), _mps())
    model = ml_model.train_isolation_forest(X, contamination=0.05)
    s = ml_model.score(model, X)
    extreme_id = X.index.max()
    assert s.loc[extreme_id, "anomaly_score"] >= s["anomaly_score"].quantile(0.9)

    reasons = ml_model.explain_projects(X, [extreme_id], ml_model.population_stats(X))
    assert isinstance(reasons[extreme_id], str) and reasons[extreme_id]
