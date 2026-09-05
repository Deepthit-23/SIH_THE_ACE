"""Feature engineering shared by the rule engine (Phase 3) and the ML model (Phase 4).

Pure pandas -- no DB access. Given the data reality:
  - there is no start_date anywhere -> build-duration / spend-velocity features
    are not derivable and are deliberately omitted;
  - there are no unit counts -> "cost per unit" is approximated by raw amount
    compared within a (state, derived_category) peer group;
  - contractor data only exists at the vendor-transaction level, aggregated here
    per MP + constituency.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.pipeline import SNAPSHOT_DATE

STALE_RECOMMENDATION_DAYS = 365
MIN_GROUP_SIZE = 15  # below this, fall back to the state-level peer group


# --------------------------------------------------------------------------- #
# Project-level features
# --------------------------------------------------------------------------- #
def add_project_features(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of `df` with engineered feature columns added.

    Expects columns: state, derived_category, sanctioned_amount, final_amount,
    recommendation_date, completion_date, status, has_images, average_rating,
    district.
    """
    out = df.copy()

    san = pd.to_numeric(out.get("sanctioned_amount"), errors="coerce")
    fin = pd.to_numeric(out.get("final_amount"), errors="coerce")
    out["amount"] = san.fillna(fin)
    out["log_amount"] = np.log1p(out["amount"].clip(lower=0))

    # Peer-group stats: (state, derived_category), with a state-only fallback for
    # thin groups so a tiny category doesn't produce meaningless z-scores.
    out["_grp"] = out["state"].fillna("?") + " | " + out["derived_category"].fillna("other")
    grp = out.groupby("_grp")["amount"]
    out["group_n"] = grp.transform("count")
    out["group_mean"] = grp.transform("mean")
    out["group_std"] = grp.transform("std")
    out["group_median"] = grp.transform("median")

    state_grp = out.groupby(out["state"].fillna("?"))["amount"]
    state_mean = state_grp.transform("mean")
    state_std = state_grp.transform("std")
    state_median = state_grp.transform("median")

    use_state = out["group_n"] < MIN_GROUP_SIZE
    eff_mean = out["group_mean"].where(~use_state, state_mean)
    eff_std = out["group_std"].where(~use_state, state_std)
    eff_median = out["group_median"].where(~use_state, state_median)

    out["peer_scope"] = np.where(use_state, "state", "state+category")
    out["amount_z"] = ((out["amount"] - eff_mean) / eff_std.replace(0, np.nan)).fillna(0.0)
    out["amount_ratio_to_median"] = (out["amount"] / eff_median.replace(0, np.nan)).fillna(1.0)
    out["peer_mean_amount"] = eff_mean
    out["peer_median_amount"] = eff_median

    # Recommendation age / staleness (recommended works only).
    rec = pd.to_datetime(out.get("recommendation_date"), errors="coerce")
    snap = pd.Timestamp(SNAPSHOT_DATE)
    out["days_since_recommendation"] = (snap - rec).dt.days
    out["is_stale_recommendation"] = (
        (out["status"] == "recommended")
        & (out["days_since_recommendation"] > STALE_RECOMMENDATION_DAYS)
    ).fillna(False)

    out["has_images_int"] = out.get("has_images").astype("boolean").fillna(False).astype(int)
    out["rating"] = pd.to_numeric(out.get("average_rating"), errors="coerce")
    out["district_missing"] = out.get("district").isna().astype(int)

    return out.drop(columns=["_grp"])


# --------------------------------------------------------------------------- #
# Vendor / contractor concentration  (from vendor_transactions)
# --------------------------------------------------------------------------- #
def vendor_concentration(vtx: pd.DataFrame) -> pd.DataFrame:
    """Per (mp_name, constituency, vendor): volume + share of that MP's spend.

    Expects columns: mp_name, constituency, state, vendor, amount, payment_status.
    """
    v = vtx.copy()
    v["amount"] = pd.to_numeric(v["amount"], errors="coerce").fillna(0.0)
    v["vendor"] = v["vendor"].fillna("UNKNOWN").str.strip()
    v["_unit"] = v["mp_name"].fillna("?") + " || " + v["constituency"].fillna("?")

    in_prog = v["payment_status"].fillna("").str.contains("In-Progress", case=False)
    v["in_progress_amount"] = v["amount"].where(in_prog, 0.0)

    per_vendor = v.groupby(["_unit", "mp_name", "constituency", "state", "vendor"]).agg(
        txn_count=("amount", "size"),
        total_amount=("amount", "sum"),
        in_progress_amount=("in_progress_amount", "sum"),
    ).reset_index()

    unit_tot = v.groupby("_unit").agg(
        unit_txn_count=("amount", "size"),
        unit_total_amount=("amount", "sum"),
        unit_vendor_count=("vendor", "nunique"),
    ).reset_index()

    m = per_vendor.merge(unit_tot, on="_unit", how="left")
    m["share_of_unit_value"] = (m["total_amount"] / m["unit_total_amount"].replace(0, np.nan)).fillna(0.0)
    m["share_of_unit_count"] = (m["txn_count"] / m["unit_txn_count"].replace(0, np.nan)).fillna(0.0)
    return m.drop(columns=["_unit"])


def mp_payment_gap(vtx: pd.DataFrame, mp_summary: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per (mp_name, constituency): in-progress payment exposure.

    If `mp_summary` is provided (cols mp_name, constituency, utilization_pct,
    balance_unpaid), it is joined for cross-check.
    """
    v = vtx.copy()
    v["amount"] = pd.to_numeric(v["amount"], errors="coerce").fillna(0.0)
    in_prog = v["payment_status"].fillna("").str.contains("In-Progress", case=False)
    v["in_progress_amount"] = v["amount"].where(in_prog, 0.0)

    g = v.groupby(["mp_name", "constituency"]).agg(
        txn_count=("amount", "size"),
        total_amount=("amount", "sum"),
        in_progress_amount=("in_progress_amount", "sum"),
        in_progress_count=("in_progress_amount", lambda s: int((s > 0).sum())),
    ).reset_index()
    g["in_progress_value_share"] = (
        g["in_progress_amount"] / g["total_amount"].replace(0, np.nan)
    ).fillna(0.0)

    if mp_summary is not None and not mp_summary.empty:
        cols = ["mp_name", "constituency", "utilization_pct", "balance_unpaid"]
        have = [c for c in cols if c in mp_summary.columns]
        g = g.merge(mp_summary[have], on=["mp_name", "constituency"], how="left")

    return g


PROJECT_ML_FEATURES = [
    "log_amount",
    "amount_z",
    "amount_ratio_to_median",
    "days_since_recommendation",
    "has_images_int",
    "district_missing",
]
