"""Rule engine for MPLAD anomaly detection (Phase 3).

Four independent, pure rule functions. Each takes a dataframe (or two) and
returns a tidy dataframe of flags with a plain-language `reason` string. No DB
access, no API coupling -- unit-testable with a handful of hand-built rows.

Grain of each rule:
  - cost_anomaly            -> one row per project
  - contractor_concentration-> one row per (vendor, geo-unit)
  - stalled_project         -> one row per recommended project
  - payment_gap             -> one row per (mp_name, constituency)

Thresholds are module-level constants so they can be tuned from the evaluation
script (see `evaluate_rules.py`).
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

from app.pipeline import SNAPSHOT_DATE

# --- tunable thresholds ---------------------------------------------------- #
COST_Z_THRESHOLD = 2.5
COST_MIN_RATIO = 2.0        # also require >= 2x the peer mean (defensible reason)
COST_MIN_GROUP = 8          # need at least this many peers to judge a cost

CONTRACTOR_SHARE_THRESHOLD = 0.40   # of count OR value within (MP, geo-unit)
CONTRACTOR_MIN_UNIT_TXNS = 10
CONTRACTOR_MIN_VENDOR_TXNS = 3

STALLED_MIN_AGE_DAYS = 540            # 18 months: real works genuinely take 1-2 yrs
STALLED_MAX_MP_COMPLETION_RATE = 40.0 # only if the MP broadly under-delivers
STALLED_FUZZY_COMPLETED = 90   # token_set_ratio cutoff: recommended vs completed
STALLED_FUZZY_VENDOR = 90      # token_set_ratio cutoff: recommended vs expenditure
                               # (expenditure descriptions are generic -> keep strict)

PAYMENT_INPROGRESS_SHARE_THRESHOLD = 0.20   # in-progress value / total value
PAYMENT_MIN_TXNS = 5
PAYMENT_MIN_UTILISATION = 30.0   # only contradictory if the MP also claims util.

_DAYS_PER_MONTH = 30.44
_non_alnum = re.compile(r"[^a-z0-9 ]+")
_ws = re.compile(r"\s+")


def _norm(text: object) -> str:
    if text is None or (isinstance(text, float) and np.isnan(text)):
        return ""
    return _ws.sub(" ", _non_alnum.sub(" ", str(text).lower())).strip()


def _amount(df: pd.DataFrame) -> pd.Series:
    """Coalesced project amount: sanctioned first, then final."""
    san = pd.to_numeric(df.get("sanctioned_amount"), errors="coerce")
    fin = pd.to_numeric(df.get("final_amount"), errors="coerce")
    return san.fillna(fin)


# ======================================================================= #
# Rule 1 — Cost anomaly
# ======================================================================= #
def cost_anomaly(projects: pd.DataFrame, z_threshold: float = COST_Z_THRESHOLD) -> pd.DataFrame:
    """Flag projects whose amount is an extreme high outlier within its
    derived_category + district peer group (falling back to
    derived_category + state when district is missing or the group is thin).

    Returns a frame indexed by project id: flagged, reason, amount_z,
    amount_ratio, peer_scope, peer_label.
    """
    df = projects.reset_index(drop=True).copy()
    amt = _amount(df)
    dc = df["derived_category"].fillna("other").astype(str)
    st = df["state"].fillna("?").astype(str)
    dist = df["district"]
    has_dist = dist.notna()

    prim_key = np.where(
        has_dist, "D:" + dc + "|" + dist.fillna("").astype(str), "S:" + dc + "|" + st
    )
    state_key = "S:" + dc + "|" + st
    work = df.assign(_amt=amt, _pk=prim_key, _sk=state_key)

    pg = work.groupby("_pk")["_amt"]
    p_n, p_mean, p_std = pg.transform("count"), pg.transform("mean"), pg.transform("std")
    sg = work.groupby("_sk")["_amt"]
    s_n, s_mean, s_std = sg.transform("count"), sg.transform("mean"), sg.transform("std")

    use_fb = (p_n < COST_MIN_GROUP) | (~has_dist)
    eff_n = p_n.where(~use_fb, s_n)
    eff_mean = p_mean.where(~use_fb, s_mean)
    eff_std = p_std.where(~use_fb, s_std)
    label = pd.Series(np.where(use_fb, st, dist.fillna(st).astype(str)), index=df.index)
    scope = pd.Series(np.where(use_fb, "state", "district"), index=df.index)

    z = ((amt - eff_mean) / eff_std.replace(0, np.nan))
    ratio = (amt / eff_mean.replace(0, np.nan))

    flagged = (
        amt.notna()
        & (eff_n >= COST_MIN_GROUP)
        & (z >= z_threshold)
        & (ratio >= COST_MIN_RATIO)
    ).fillna(False)

    dc_pretty = dc.str.replace("_", " ")
    reason = pd.Series([None] * len(df), index=df.index, dtype=object)
    for i in df.index[flagged.to_numpy()]:
        reason.at[i] = (
            f"Cost is {ratio.at[i]:.1f}x the {dc_pretty.at[i]} average for {label.at[i]}"
        )

    out = pd.DataFrame(
        {
            "flagged": flagged.to_numpy(),
            "reason": reason.to_numpy(),
            "amount_z": z.round(2).to_numpy(),
            "amount_ratio": ratio.round(2).to_numpy(),
            "peer_scope": scope.to_numpy(),
            "peer_label": label.to_numpy(),
        },
        index=(df["id"].to_numpy() if "id" in df.columns else df.index),
    )
    out.index.name = "project_id"
    return out


# ======================================================================= #
# Rule 2 — Contractor / vendor concentration
# ======================================================================= #
def _geo_unit(vtx: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """(unit_label, unit_type) -- constituency, or state for Rajya Sabha rows."""
    is_rs = vtx["house"].fillna("").str.strip().eq("Rajya Sabha") | vtx[
        "constituency"
    ].fillna("").str.contains("Rajya Sabha", case=False)
    label = np.where(is_rs, vtx["state"].fillna("?"), vtx["constituency"].fillna("?"))
    utype = np.where(is_rs, "state", "constituency")
    return pd.Series(label, index=vtx.index), pd.Series(utype, index=vtx.index)


def contractor_concentration(
    vendor_transactions: pd.DataFrame,
    share_threshold: float = CONTRACTOR_SHARE_THRESHOLD,
) -> pd.DataFrame:
    """Flag vendors that hold an outsized share of an MP's transaction count or
    value within a geo-unit (constituency, or state for Rajya Sabha rows).

    Grain: one row per (mp_name, vendor, unit). Grouping within the MP -- not the
    whole constituency -- because capture happens at the level of one MP's
    allocations.

    Returns: flagged, reason, share_count, share_value, txn_count, unit_txn_count.
    """
    v = vendor_transactions.copy()
    v["amount"] = pd.to_numeric(v["amount"], errors="coerce").fillna(0.0)
    v["vendor"] = v["vendor"].fillna("UNKNOWN").astype(str).str.strip()
    v["_mp"] = v["mp_name"].fillna("?").astype(str)
    label, utype = _geo_unit(v)
    v["_unit"] = label
    v["_utype"] = utype

    per = (
        v.groupby(["_mp", "_unit", "_utype", "vendor"])
        .agg(txn_count=("amount", "size"), txn_value=("amount", "sum"))
        .reset_index()
    )
    unit = (
        v.groupby(["_mp", "_unit"])
        .agg(
            unit_txn_count=("amount", "size"),
            unit_txn_value=("amount", "sum"),
            unit_vendor_count=("vendor", "nunique"),
        )
        .reset_index()
    )
    m = per.merge(unit, on=["_mp", "_unit"], how="left")
    m["share_count"] = m["txn_count"] / m["unit_txn_count"].replace(0, np.nan)
    m["share_value"] = m["txn_value"] / m["unit_txn_value"].replace(0, np.nan)
    m[["share_count", "share_value"]] = m[["share_count", "share_value"]].fillna(0.0)

    m["flagged"] = (
        (m["unit_txn_count"] >= CONTRACTOR_MIN_UNIT_TXNS)
        & (m["txn_count"] >= CONTRACTOR_MIN_VENDOR_TXNS)
        & (m["unit_vendor_count"] >= 2)
        & ((m["share_count"] >= share_threshold) | (m["share_value"] >= share_threshold))
    )

    def _reason(r: pd.Series) -> str | None:
        if not r["flagged"]:
            return None
        if r["share_count"] >= r["share_value"]:
            pct, what = round(r["share_count"] * 100), "transactions"
        else:
            pct, what = round(r["share_value"] * 100), "transaction value"
        return (
            f"Vendor {r['vendor']} accounts for {pct}% of {what} for "
            f"{r['_mp']} in {r['_unit']}"
        )

    m["reason"] = m.apply(_reason, axis=1)
    return m.rename(
        columns={"_mp": "mp_name", "_unit": "unit", "_utype": "unit_type"}
    )[
        [
            "mp_name", "vendor", "unit", "unit_type", "flagged", "reason",
            "share_count", "share_value", "txn_count", "unit_txn_count",
        ]
    ]


# ======================================================================= #
# Rule 3 — Stalled / ghost project
# ======================================================================= #
def _has_fuzzy_match(
    cand_desc: pd.Series, cand_mp: pd.Series, pool_desc: pd.Series, pool_mp: pd.Series,
    cutoff: float,
) -> pd.Series:
    """For each candidate: is there a work in `pool` with the SAME (normalised)
    MP name and a fuzzily-matching description? Blocked by MP name so this stays
    cheap.
    """
    pool = pd.DataFrame({"_mp": pool_mp.map(_norm), "_d": pool_desc.map(_norm)})
    pool = pool[pool["_d"] != ""]
    by_mp: dict[str, list[str]] = {
        mp: grp["_d"].tolist() for mp, grp in pool.groupby("_mp") if mp
    }
    out = []
    for d, mp in zip(cand_desc.map(_norm), cand_mp.map(_norm)):
        choices = by_mp.get(mp)
        if not d or not choices:
            out.append(False)
            continue
        hit = process.extractOne(
            d, choices, scorer=fuzz.token_set_ratio, score_cutoff=cutoff
        )
        out.append(hit is not None)
    return pd.Series(out, index=cand_desc.index)


def stalled_project(
    projects: pd.DataFrame,
    vendor_transactions: pd.DataFrame,
    mp_summary: pd.DataFrame | None = None,
    min_age_days: int = STALLED_MIN_AGE_DAYS,
    use_fuzzy: bool = True,
) -> pd.DataFrame:
    """Flag recommended works that are old AND show no downstream activity AND
    belong to an MP that broadly under-delivers.

    The recommended and completed populations barely overlap in this data, so
    "no completed match" alone is far too broad. We stack three independent
    signals:
      1. recommended > `min_age_days` old (default 18 months);
      2. no fuzzily-matching completed work AND no fuzzily-matching expenditure
         (both blocked on normalised MP name);
      3. if `mp_summary` is given, the MP's completion_rate_pct is below
         `STALLED_MAX_MP_COMPLETION_RATE` (or missing).

    Set `use_fuzzy=False` for the simple variant (MP has no completed work / no
    expenditure at all).

    Returns a frame indexed by project id (recommended rows only): flagged,
    reason, months_since_recommendation, has_completed_match, has_vendor_match.
    """
    df = projects.reset_index(drop=True).copy()
    vtx = vendor_transactions
    if len(vtx) == 0 or "mp_name" not in vtx.columns:
        vtx = pd.DataFrame({"work_description": [], "mp_name": []})

    rec_date = pd.to_datetime(df.get("recommendation_date"), errors="coerce")
    age_days = (pd.Timestamp(SNAPSHOT_DATE) - rec_date).dt.days
    is_rec = df["status"].astype(str).eq("recommended")

    low_delivery = pd.Series(True, index=df.index)
    if mp_summary is not None and not mp_summary.empty:
        rate = (
            mp_summary.dropna(subset=["mp_name"])
            .drop_duplicates(["mp_name", "constituency"])
            .set_index(["mp_name", "constituency"])["completion_rate_pct"]
        )
        key = list(zip(df["mp_name"], df["constituency"]))
        mp_rate = pd.Series([rate.get(k) for k in key], index=df.index)
        low_delivery = mp_rate.isna() | (mp_rate < STALLED_MAX_MP_COMPLETION_RATE)

    cand_mask = is_rec & (age_days > min_age_days) & low_delivery
    cand = df[cand_mask]

    completed = df[df["status"].astype(str).eq("completed")]

    if use_fuzzy and len(cand):
        has_completed = _has_fuzzy_match(
            cand["work_description"], cand["mp_name"],
            completed["work_description"], completed["mp_name"],
            STALLED_FUZZY_COMPLETED,
        )
        has_vendor = _has_fuzzy_match(
            cand["work_description"], cand["mp_name"],
            vtx["work_description"], vtx["mp_name"],
            STALLED_FUZZY_VENDOR,
        )
    else:
        # v1-simple: does this MP have ANY completed work / ANY expenditure?
        mp_norm = cand["mp_name"].map(_norm)
        completed_mps = set(completed["mp_name"].map(_norm))
        vendor_mps = set(vtx["mp_name"].map(_norm))
        has_completed = mp_norm.isin(completed_mps)
        has_vendor = mp_norm.isin(vendor_mps)

    flagged_cand = ~(has_completed | has_vendor)
    months = (age_days / _DAYS_PER_MONTH).round()  # float, NaN for non-recommended

    flagged = pd.Series(False, index=df.index)
    reason = pd.Series([None] * len(df), index=df.index, dtype=object)
    hc = pd.Series(pd.NA, index=df.index, dtype="object")
    hv = pd.Series(pd.NA, index=df.index, dtype="object")
    if len(cand):
        flagged.loc[cand.index] = flagged_cand.to_numpy()
        hc.loc[cand.index] = has_completed.to_numpy()
        hv.loc[cand.index] = has_vendor.to_numpy()
        for i in cand.index[flagged_cand.to_numpy()]:
            reason.at[i] = (
                f"Recommended {int(months.at[i])} months ago, no completion or "
                f"payment activity recorded"
            )

    out = pd.DataFrame(
        {
            "flagged": flagged.to_numpy(),
            "reason": reason.to_numpy(),
            "months_since_recommendation": months.to_numpy(),
            "has_completed_match": hc.to_numpy(),
            "has_vendor_match": hv.to_numpy(),
        }
    )
    out.index = df["id"].to_numpy() if "id" in df.columns else df.index
    out.index.name = "project_id"
    # only the recommended rows are in scope for this rule
    return out[is_rec.to_numpy()]


# ======================================================================= #
# Rule 4 — Payment-gap anomaly
# ======================================================================= #
def payment_gap(
    vendor_transactions: pd.DataFrame,
    mp_summary: pd.DataFrame | None = None,
    share_threshold: float = PAYMENT_INPROGRESS_SHARE_THRESHOLD,
) -> pd.DataFrame:
    """Flag MPs whose in-progress payment *value* is a large share of their total
    transaction value while overall utilisation is nonetheless high.

    Returns one row per (mp_name, constituency): flagged, reason,
    in_progress_share, utilization_pct, txn_count.
    """
    v = vendor_transactions.copy()
    v["amount"] = pd.to_numeric(v["amount"], errors="coerce").fillna(0.0)
    in_prog = v["payment_status"].fillna("").str.contains("In-Progress", case=False)
    v["_ip"] = v["amount"].where(in_prog, 0.0)

    g = (
        v.groupby(["mp_name", "constituency"])
        .agg(
            txn_count=("amount", "size"),
            total_value=("amount", "sum"),
            in_progress_value=("_ip", "sum"),
        )
        .reset_index()
    )
    g["in_progress_share"] = g["in_progress_value"] / g["total_value"].replace(0, np.nan)
    g["in_progress_share"] = g["in_progress_share"].fillna(0.0)

    if mp_summary is not None and not mp_summary.empty:
        s = mp_summary[["mp_name", "constituency", "utilization_pct"]].drop_duplicates(
            ["mp_name", "constituency"]
        )
        g = g.merge(s, on=["mp_name", "constituency"], how="left")
    else:
        g["utilization_pct"] = np.nan

    util = pd.to_numeric(g["utilization_pct"], errors="coerce")
    g["flagged"] = (
        (g["txn_count"] >= PAYMENT_MIN_TXNS)
        & (g["in_progress_share"] >= share_threshold)
        & (util.isna() | (util >= PAYMENT_MIN_UTILISATION))
    )

    def _reason(r: pd.Series) -> str | None:
        if not r["flagged"]:
            return None
        x = round(r["in_progress_share"] * 100)
        y = r["utilization_pct"]
        ytxt = f"{round(y)}%" if pd.notna(y) else "unknown"
        return (
            f"{x}% of this MP's payment value is still in-progress despite "
            f"{ytxt} overall utilization"
        )

    g["reason"] = g.apply(_reason, axis=1)
    return g[
        [
            "mp_name", "constituency", "flagged", "reason",
            "in_progress_share", "utilization_pct", "txn_count",
        ]
    ]
