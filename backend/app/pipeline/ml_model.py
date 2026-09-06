"""Unsupervised anomaly detector (Isolation Forest) + feature-deviation
explainability.

Independent of `rules.py`. The model is trained ONLY on engineered features --
`is_synthetic_anomaly` / `anomaly_type` are never fed in (evaluation only).

One feature row per project. Signals that are naturally at (MP, constituency)
grain -- vendor concentration, payment gap, MP completion rate -- are joined
*down* to project level as extra columns so the model works at the same grain as
the rule engine.

Explainability: for each flagged project, rank features by robust deviation
`(value - median) / IQR` from the population and turn the top few into a
plain-language reason. (SHAP's TreeExplainer support for IsolationForest is
version-fragile; feature-deviation ranking is the deliberate choice here.)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from app.pipeline.categorize import all_categories
from app.pipeline.features import (
    add_project_features,
    mp_payment_gap,
    vendor_concentration,
)

RANDOM_STATE = 42

NUMERIC_FEATURES = [
    "log_amount",
    "amount_z",
    "amount_ratio_to_median",
    "days_since_recommendation",
    "status_recommended",
    "mp_completion_rate_pct",
    "mp_in_progress_share",
    "mp_max_vendor_value_share",
    "mp_max_vendor_count_share",
    "mp_vendor_count_log",
    "mp_txn_count_log",
    "district_project_count_log",
    "district_amount_mean_log",
    "has_images_int",
    "district_missing",
    "is_rajya_sabha_int",
]
CATEGORY_FEATURES = [f"dc_{c}" for c in all_categories()]
FEATURE_COLUMNS = NUMERIC_FEATURES + CATEGORY_FEATURES

# feature -> (direction, sentence fragment). direction +1: high is suspicious,
# -1: low is suspicious. Only these features appear in ML explanations, and they
# are surfaced in THIS fixed priority order (not by raw deviation magnitude, which
# was unstable and produced shuffled-looking text). `amount_z` and
# `mp_max_vendor_count_share` were dropped -- near-collinear with the entries kept.
EXPLAIN_FEATURES: dict[str, tuple[int, str]] = {
    "amount_ratio_to_median": (1, "the cost is many times the typical amount for similar projects"),
    "log_amount": (1, "the absolute amount involved is very large"),
    "mp_max_vendor_value_share": (1, "one vendor takes an outsized share of this MP's spending"),
    "mp_in_progress_share": (1, "a large share of this MP's payments are stuck in-progress"),
    "district_amount_mean_log": (1, "project costs across this whole district run high"),
    "days_since_recommendation": (1, "it was recommended long ago with little recorded activity"),
    "mp_completion_rate_pct": (-1, "this MP completes unusually few of its works"),
}


# --------------------------------------------------------------------------- #
# feature assembly
# --------------------------------------------------------------------------- #
def mp_aggregates(vtx: pd.DataFrame, mp_summary: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per (mp_name, constituency): vendor-concentration + payment-gap signals."""
    cols = [
        "mp_name", "constituency", "mp_max_vendor_value_share",
        "mp_max_vendor_count_share", "mp_vendor_count", "mp_txn_count",
        "mp_in_progress_share",
    ]
    if vtx is None or len(vtx) == 0:
        return pd.DataFrame(columns=cols)

    vc = vendor_concentration(vtx)
    if len(vc):
        g = (
            vc.groupby(["mp_name", "constituency"])
            .agg(
                mp_max_vendor_value_share=("share_of_unit_value", "max"),
                mp_max_vendor_count_share=("share_of_unit_count", "max"),
                mp_vendor_count=("unit_vendor_count", "max"),
                mp_txn_count=("unit_txn_count", "max"),
            )
            .reset_index()
        )
    else:
        g = pd.DataFrame(columns=cols[:-1])

    pg = mp_payment_gap(vtx, mp_summary)
    pg = pg.rename(columns={"in_progress_value_share": "mp_in_progress_share"})[
        ["mp_name", "constituency", "mp_in_progress_share"]
    ]
    return g.merge(pg, on=["mp_name", "constituency"], how="outer")


def build_feature_matrix(
    projects: pd.DataFrame,
    vtx: pd.DataFrame,
    mp_summary: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return the numeric feature matrix, indexed by project id."""
    f = add_project_features(projects).reset_index(drop=True)

    f["status_recommended"] = f["status"].astype(str).eq("recommended").astype(int)
    f["is_rajya_sabha_int"] = (
        f.get("is_rajya_sabha", pd.Series(False, index=f.index))
        .astype("boolean").fillna(False).astype(int)
    )
    f["days_since_recommendation"] = pd.to_numeric(
        f["days_since_recommendation"], errors="coerce"
    ).fillna(-1.0)

    amount = pd.to_numeric(f["amount"], errors="coerce")
    dgrp = f.assign(_a=amount).groupby(f["district"].fillna("?"))["_a"]
    f["district_project_count_log"] = np.log1p(dgrp.transform("count").fillna(0))
    f["district_amount_mean_log"] = np.log1p(
        dgrp.transform("mean").fillna(amount.median())
    )

    agg = mp_aggregates(vtx, mp_summary)
    if len(agg):
        f = f.merge(agg, on=["mp_name", "constituency"], how="left")

    if mp_summary is not None and not mp_summary.empty:
        s = mp_summary.drop_duplicates(["mp_name", "constituency"])[
            ["mp_name", "constituency", "completion_rate_pct"]
        ].rename(columns={"completion_rate_pct": "mp_completion_rate_pct"})
        f = f.merge(s, on=["mp_name", "constituency"], how="left")
    if "mp_completion_rate_pct" not in f:
        f["mp_completion_rate_pct"] = np.nan

    for c in ["mp_max_vendor_value_share", "mp_max_vendor_count_share", "mp_in_progress_share"]:
        f[c] = pd.to_numeric(f.get(c), errors="coerce").fillna(0.0)
    f["mp_vendor_count_log"] = np.log1p(
        pd.to_numeric(f.get("mp_vendor_count"), errors="coerce").fillna(0.0)
    )
    f["mp_txn_count_log"] = np.log1p(
        pd.to_numeric(f.get("mp_txn_count"), errors="coerce").fillna(0.0)
    )
    med_cr = pd.to_numeric(f["mp_completion_rate_pct"], errors="coerce").median()
    f["mp_completion_rate_pct"] = pd.to_numeric(
        f["mp_completion_rate_pct"], errors="coerce"
    ).fillna(med_cr if pd.notna(med_cr) else 0.0)

    f["amount_z"] = pd.to_numeric(f["amount_z"], errors="coerce").fillna(0.0)
    f["amount_ratio_to_median"] = pd.to_numeric(
        f["amount_ratio_to_median"], errors="coerce"
    ).fillna(1.0)
    f["log_amount"] = pd.to_numeric(f["log_amount"], errors="coerce").fillna(0.0)
    f["has_images_int"] = pd.to_numeric(f.get("has_images_int"), errors="coerce").fillna(0)
    f["district_missing"] = pd.to_numeric(f.get("district_missing"), errors="coerce").fillna(0)

    dc = f["derived_category"].fillna("other")
    for c in all_categories():
        f[f"dc_{c}"] = dc.eq(c).astype(int)

    X = f.reindex(columns=FEATURE_COLUMNS).astype(float).fillna(0.0)
    X.index = f["id"].to_numpy() if "id" in f.columns else f.index
    X.index.name = "project_id"
    return X


# --------------------------------------------------------------------------- #
# model
# --------------------------------------------------------------------------- #
def train_isolation_forest(
    X: pd.DataFrame,
    contamination: float = 0.03,
    n_estimators: int = 200,
    random_state: int = RANDOM_STATE,
) -> IsolationForest:
    model = IsolationForest(
        n_estimators=n_estimators,
        contamination=contamination,
        max_samples="auto",
        random_state=random_state,
        n_jobs=-1,
    )
    model.fit(X.to_numpy())
    return model


def score(model: IsolationForest, X: pd.DataFrame) -> pd.DataFrame:
    """Return per-project: anomaly_score (higher = worse), ml_percentile, ml_flag."""
    raw = -model.decision_function(X.to_numpy())  # flip so higher = more anomalous
    pred = model.predict(X.to_numpy())
    pct = pd.Series(raw, index=X.index).rank(pct=True) * 100.0
    return pd.DataFrame(
        {
            "anomaly_score": raw,
            "ml_percentile": pct.to_numpy(),
            "ml_flag": pred == -1,
        },
        index=X.index,
    )


# --------------------------------------------------------------------------- #
# explainability
# --------------------------------------------------------------------------- #
def population_stats(X: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    med = X.median()
    iqr = (X.quantile(0.75) - X.quantile(0.25)).replace(0, np.nan)
    return med, iqr


def explain_fragments(
    X: pd.DataFrame,
    flagged_index,
    stats: tuple[pd.Series, pd.Series] | None = None,
    min_dev: float = 1.2,
) -> dict:
    """Per flagged project id: list of (feature, fragment) that deviate, in the
    fixed EXPLAIN_FEATURES priority order (NOT sorted by magnitude).

    Returns ALL qualifying fragments -- the caller (risk_scorer.combine) drops
    the ones a fired rule already covers and then takes the top few.
    """
    med, iqr = stats if stats is not None else population_stats(X)
    out: dict = {}
    for pid, row in X.loc[list(flagged_index)].iterrows():
        frags: list[tuple[str, str]] = []
        for feat, (direction, frag) in EXPLAIN_FEATURES.items():
            denom = iqr[feat] if pd.notna(iqr.get(feat)) else 1.0
            dev = (row[feat] - med[feat]) / denom * direction
            if dev >= min_dev:
                frags.append((feat, frag))
        out[pid] = frags
    return out


def explain_projects(
    X: pd.DataFrame,
    flagged_index,
    stats: tuple[pd.Series, pd.Series] | None = None,
    top_n: int = 3,
    min_dev: float = 1.2,
) -> dict:
    """Plain-language reason string per flagged project id (standalone use).

    `risk_scorer.combine` uses `explain_fragments` directly so it can suppress
    fragments already covered by a fired rule.
    """
    frag_map = explain_fragments(X, flagged_index, stats, min_dev)
    out: dict = {}
    for pid, frags in frag_map.items():
        picked = [f for _, f in frags[:top_n]]
        out[pid] = (
            "Anomaly model: " + "; ".join(picked)
            if picked
            else "Anomaly model flagged an unusual combination of attributes"
        )
    return out
