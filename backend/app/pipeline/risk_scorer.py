"""Risk combiner: fuse the rule engine and the ML anomaly score into one
0-100 `combined_risk_score` per project + an ordered explanation list.

Imports both detectors' *outputs* (not their internals). The two detectors stay
independent; this module only decides how to weigh and merge them.

Weighting rationale (points reflect BOTH precision and grain):
        cost_anomaly             40   project-grain, precise (FP 2.2%) -- about THIS project's price
        contractor_concentration 30   MP-grain: precise at flagging a compromised MP (FP 0.6% of
                                      groups) but shared across that MP's whole portfolio, so it
                                      is not a 45-point signal for each individual project
        payment_gap              25   MP-grain, same reasoning (FP 2.9% of groups)
        stalled_project          15   project-grain but weak (FP 8.5%) -- a watchlist signal
  The MP-grain signals surface at full strength in the Phase 5 pattern view.

Score construction:
  - rule_score = sum of triggered points (NOT capped -- 4 flags = 110 must beat 3 = 95).
  - ml_score   = 0 below the ML_REASON_MIN_PERCENTILE (p92); [p92, p100] -> [0, 80].
                 It contributes to the score ONLY where it also produces a reason.
  - base       = soft_knee(max(rule, ml) + 0.25 * min(rule, ml)) -- a smooth knee at 70
                 asymptotic to 88, so stacked points can't pin thousands of rows at 100.
  - tie-break  = up to +14 from |cost z-score| (COST_TIEBREAK_*), applied ONLY when the
                 cost rule fired. This is the continuous, project-specific signal that
                 separates a 3x overrun from a 51x overrun inside one MP's cluster.
  - combined   = min(100, base + tie-break). Reaching ~99 needs a fired cost rule with a
                 huge z-score; the top of the scale is genuinely hard to hit.

Explanation consistency:
  - every point-contributor (each fired rule, and ML when include_ml) appears in the list;
  - a project with score > 0 always has a non-empty explanation;
  - ML fragments that a fired rule already covers (RULE_COVERS) are dropped -- ML text
    adds information rather than restating a rule -- surfaced in fixed priority order.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

RULE_POINTS: dict[str, int] = {
    "cost_anomaly": 40,
    "contractor_concentration": 30,
    "payment_gap": 25,
    "stalled_project": 15,
}
ML_WEIGHT = 0.8
WEAK_SIGNAL_FACTOR = 0.25

# --- score-shape controls (Fix 2: no hard cap; discriminate in the 80-100 band) ---
# The combined-signal base is squashed with a smooth knee so that stacking rule
# points can't pin thousands of projects at exactly 100. Without the cost
# tie-breaker below, the base alone asymptotes to BASE_SOFT_ASYMPTOTE.
BASE_SOFT_KNEE = 70.0
BASE_SOFT_ASYMPTOTE = 88.0
# The top ~12 points of the scale are reserved for a continuous, genuinely
# project-specific signal: the magnitude of the cost z-score (only when the cost
# rule actually fired, so it always corresponds to a shown reason). This is what
# separates a 3x overrun from a 51x overrun inside the same MP's cluster.
COST_TIEBREAK_MAX = 14.0
COST_TIEBREAK_Z_FULL = 15.0


def _soft_knee(x, knee: float, asymptote: float):
    """Linear below `knee`; smoothly asymptotic to `asymptote` above it."""
    span = asymptote - knee
    x = np.asarray(x, dtype=float)
    return np.where(x <= knee, x, asymptote - span * np.exp(-(x - knee) / span))


# When a rule fires, the ML fragments listed here say the same thing -- suppress
# them from the ML explanation so its text adds information, not restatement.
RULE_COVERS: dict[str, set[str]] = {
    "cost_anomaly": {"amount_ratio_to_median"},
    "contractor_concentration": {"mp_max_vendor_value_share"},
    "payment_gap": {"mp_in_progress_share"},
    "stalled_project": {"days_since_recommendation", "mp_completion_rate_pct"},
}
_ML_TOP_N = 3

# The ML percentile is uniform by construction, so a linear map would score the
# median project 50/100. ML only contributes -- to BOTH the score and the
# explanation -- at/above this percentile (or on a hard model flag). Below it the
# ML contribution is 0: the model may not silently push a score up without also
# being able to show a reason. [floor, 100] is stretched to [0, 1].
ML_REASON_MIN_PERCENTILE = 92.0

# order rule reasons in the explanation list by descending trust
_RULE_ORDER = sorted(RULE_POINTS, key=RULE_POINTS.get, reverse=True)
_RULE_LABEL = {
    "cost_anomaly": "Cost anomaly",
    "contractor_concentration": "Contractor concentration",
    "payment_gap": "Payment gap",
    "stalled_project": "Stalled / ghost project",
}


def _reindex_flag(df: pd.DataFrame, index, col: str = "flagged") -> pd.Series:
    if df is None or col not in getattr(df, "columns", []):
        return pd.Series(False, index=index)
    return df[col].astype(bool).reindex(index, fill_value=False)


def combine(
    projects: pd.DataFrame,
    cost_df: pd.DataFrame,
    stalled_df: pd.DataFrame,
    contractor_df: pd.DataFrame,
    payment_df: pd.DataFrame,
    ml_df: pd.DataFrame,
    ml_fragments: dict | None = None,
) -> pd.DataFrame:
    """Produce per-project scores + explanations.

    Inputs (all as returned by the detector modules):
      cost_df, stalled_df : indexed by project_id, cols [flagged, reason, amount_z]
      contractor_df       : cols [mp_name, vendor, unit, flagged, reason,
                                  share_count, share_value]
      payment_df          : cols [mp_name, constituency, flagged, reason]
      ml_df               : indexed by project_id, cols [anomaly_score,
                                  ml_percentile, ml_flag, ml_reason]
      ml_fragments        : optional {project_id -> [(feature, fragment), ...]}
                            from ml_model.explain_fragments. When given, the ML
                            explanation drops fragments a fired rule already
                            covers (RULE_COVERS). Falls back to ml_df["ml_reason"].
    Returns a frame indexed by project_id: rule_score, ml_score,
    ml_anomaly_score, combined_risk_score, rule_flags (dict), explanation (list).
    """
    proj = projects[["id", "mp_name", "constituency"]].drop_duplicates("id").set_index("id")
    idx = proj.index

    # --- per-project rule booleans + reason strings --------------------------
    cost_flag = _reindex_flag(cost_df, idx)
    cost_reason = (
        cost_df["reason"].reindex(idx) if cost_df is not None else pd.Series(index=idx, dtype=object)
    )
    stalled_flag = _reindex_flag(stalled_df, idx)
    stalled_reason = (
        stalled_df["reason"].reindex(idx) if stalled_df is not None
        else pd.Series(index=idx, dtype=object)
    )

    # contractor: flagged at (mp, vendor, unit) -> reduce to MP + best reason
    cflag = contractor_df[contractor_df["flagged"]].copy() if contractor_df is not None else pd.DataFrame()
    if len(cflag):
        cflag["_s"] = cflag[["share_count", "share_value"]].max(axis=1)
        cflag = cflag.sort_values("_s", ascending=False).drop_duplicates("mp_name")
        contractor_reason_by_mp = cflag.set_index("mp_name")["reason"]
    else:
        contractor_reason_by_mp = pd.Series(dtype=object)
    contractor_flag = proj["mp_name"].isin(set(contractor_reason_by_mp.index))
    contractor_reason = proj["mp_name"].map(contractor_reason_by_mp)

    # payment gap: flagged at (mp, constituency)
    pflag = payment_df[payment_df["flagged"]] if payment_df is not None else pd.DataFrame()
    payment_reason_by_key = (
        pflag.set_index(["mp_name", "constituency"])["reason"] if len(pflag)
        else pd.Series(dtype=object)
    )
    keys = list(zip(proj["mp_name"], proj["constituency"]))
    pk_index = set(payment_reason_by_key.index)
    payment_flag = pd.Series([k in pk_index for k in keys], index=idx)
    payment_reason = pd.Series(
        [payment_reason_by_key.get(k) for k in keys], index=idx, dtype=object
    )

    flags = pd.DataFrame(
        {
            "cost_anomaly": cost_flag.to_numpy(bool),
            "contractor_concentration": contractor_flag.to_numpy(bool),
            "payment_gap": payment_flag.to_numpy(bool),
            "stalled_project": stalled_flag.to_numpy(bool),
        },
        index=idx,
    )

    # --- scores ------------------------------------------------------------
    # Not capped: all-four-flags (110) must be distinguishable from three (95).
    rule_score = pd.Series(0.0, index=idx)
    for code, pts in RULE_POINTS.items():
        rule_score = rule_score + flags[code].astype(float) * pts

    ml = ml_df.reindex(idx) if ml_df is not None else pd.DataFrame(index=idx)
    ml_pct = pd.to_numeric(ml.get("ml_percentile"), errors="coerce").fillna(0.0)
    ml_raw = pd.to_numeric(ml.get("anomaly_score"), errors="coerce")
    ml_flag = ml.get("ml_flag", pd.Series(False, index=idx)) == True  # noqa: E712 (NaN -> False)
    ml_reason = ml.get("ml_reason", pd.Series(index=idx, dtype=object))

    # ML contributes to the score ONLY where it can also show a reason: at/above
    # ML_REASON_MIN_PERCENTILE, or on a hard model flag. Elsewhere its
    # contribution is floored to 0 -- no score movement without an explanation.
    include_ml = ml_flag | (ml_pct >= ML_REASON_MIN_PERCENTILE)
    ml_tail = (
        (ml_pct - ML_REASON_MIN_PERCENTILE) / (100.0 - ML_REASON_MIN_PERCENTILE)
    ).clip(0.0, 1.0)
    ml_score = (ML_WEIGHT * 100.0 * ml_tail).where(include_ml, 0.0)

    # base: stronger signal sets the floor, the weaker adds a quarter -- then a
    # smooth knee so stacked points can't pin everything at 100.
    base_raw = np.maximum(rule_score, ml_score) + WEAK_SIGNAL_FACTOR * np.minimum(rule_score, ml_score)
    base = _soft_knee(base_raw, BASE_SOFT_KNEE, BASE_SOFT_ASYMPTOTE)

    # cost z-score tie-breaker (project-specific, continuous) -- only where the
    # cost rule fired, so it always corresponds to a reason in the explanation.
    if cost_df is not None and "amount_z" in cost_df.columns:
        cost_z = pd.to_numeric(cost_df["amount_z"], errors="coerce").reindex(idx).fillna(0.0)
    else:
        cost_z = pd.Series(0.0, index=idx)
    tie = (cost_z / COST_TIEBREAK_Z_FULL).clip(0.0, 1.0) * COST_TIEBREAK_MAX
    tie = tie.where(cost_flag, 0.0)

    combined = np.minimum(100.0, base + tie.to_numpy())

    # --- explanation list ------------------------------------------------
    reason_cols = {
        "cost_anomaly": cost_reason,
        "contractor_concentration": contractor_reason,
        "payment_gap": payment_reason,
        "stalled_project": stalled_reason,
    }
    include_ml_np = include_ml.to_numpy()
    flags_np = {c: flags[c].to_numpy() for c in RULE_POINTS}
    explanations: list[list[dict]] = []
    rf_dicts: list[dict] = []
    for i, pid in enumerate(idx):
        items: list[dict] = []
        for code in _RULE_ORDER:
            if flags_np[code][i]:
                msg = reason_cols[code].iloc[i]
                items.append({
                    "source": "rule",
                    "code": code,
                    "label": _RULE_LABEL[code],
                    "weight": RULE_POINTS[code],
                    "message": msg if isinstance(msg, str) and msg else _RULE_LABEL[code],
                })
        if include_ml_np[i]:
            fired = [c for c in RULE_POINTS if flags_np[c][i]]
            if ml_fragments is not None:
                covered = set().union(*(RULE_COVERS.get(c, set()) for c in fired)) if fired else set()
                frags = ml_fragments.get(pid, [])
                new_frags = [frag for feat, frag in frags if feat not in covered][:_ML_TOP_N]
                if new_frags:
                    msg = "Anomaly model: " + "; ".join(new_frags)
                elif fired:
                    # ML corroborates but adds no signal the rules don't already show
                    msg = "Anomaly model: overall profile consistent with the findings above"
                elif frags:
                    msg = "Anomaly model: " + "; ".join(f for _, f in frags[:_ML_TOP_N])
                else:
                    msg = "Anomaly model flagged an unusual combination of attributes"
            else:
                m = ml_reason.iloc[i] if hasattr(ml_reason, "iloc") else None
                msg = m if isinstance(m, str) and m else (
                    "Anomaly model flagged an unusual combination of attributes"
                )
            items.append({
                "source": "ml",
                "code": "isolation_forest",
                "label": "Anomaly model",
                "weight": round(float(ml_score.iloc[i]), 1),
                "message": msg,
            })
        explanations.append(items)
        rf_dicts.append({c: bool(flags_np[c][i]) for c in RULE_POINTS})

    out = pd.DataFrame(
        {
            "rule_score": rule_score.round(1).to_numpy(),
            "ml_score": ml_score.round(1).to_numpy(),
            "ml_anomaly_score": ml_raw.to_numpy(),
            "ml_percentile": ml_pct.round(1).to_numpy(),
            "combined_risk_score": np.round(combined, 1),
            "rule_flags": rf_dicts,
            "explanation": explanations,
        },
        index=idx,
    )
    out.index.name = "project_id"
    return out
