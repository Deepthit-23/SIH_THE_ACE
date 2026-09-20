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
from collections import Counter

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

from app.pipeline import SNAPSHOT_DATE
from app.pipeline.names import match_mps, normalize_mp_name

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

# allocation_ceiling_breach: tolerance absorbs rounding/timing differences between snapshots
ALLOCATION_TOLERANCE = 0.02

# duplicate_work: text AND amount AND date must all agree, on boilerplate-stripped descriptions.
# Measured on real rows (see RUNBOOK): text+amount alone flags ~21% (mostly multi-unit purchases
# entered in one batch: five identical water tankers, ten identical library-book lots);
# a rare-token filter brings it to 6.6%; the date gap brings it to ~1.4%.
DUPLICATE_TEXT_SIMILARITY = 90       # token_sort_ratio on the rare, non-numeric tokens
DUPLICATE_AMOUNT_TOLERANCE = 0.15    # amounts within 15% of the larger one
DUPLICATE_MIN_GAP_DAYS = 30          # same batch/date entries are multi-unit buys, not re-claims
DUPLICATE_MIN_RARE_TOKENS = 2        # specificity floor: distinctive tokens that must remain
DUPLICATE_COMMON_DF = 0.001          # a token in > 0.1% of all descriptions is boilerplate...
DUPLICATE_COMMON_DF_FLOOR = 3        # ...but never treat a token seen <=3 times as boilerplate

RECENT_TERM_MONTHS = 18

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
    use_fuzzy: bool = True, mp_allocation: pd.DataFrame | None = None,
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
    # Full suppression for a new term: an old recommendation may predate the
    # incumbent, so merely discounting the score would still misattribute the signal.
    # Term start comes from the official PDF (year only -> assumed 1 July of that year).
    # LS rows carry no term in the PDF, so they are never dampened (elected 2024 =
    # >18 months before the snapshot anyway).
    if mp_allocation is not None and not mp_allocation.empty and len(cand):
        m = match_mps(cand[["mp_name", "state"]], mp_allocation)
        m["_ts"] = m["alloc_index"].map(mp_allocation["term_start"]) if "term_start" in mp_allocation else np.nan
        term_months = (SNAPSHOT_DATE.year - m["_ts"]) * 12 + (SNAPSHOT_DATE.month - 7)
        m["_recent"] = m["_ts"].notna() & (term_months < RECENT_TERM_MONTHS)
        rec = cand[["mp_name", "state"]].merge(
            m[["mp_name", "state", "_recent"]], on=["mp_name", "state"], how="left"
        )
        recent = pd.Series(rec["_recent"].fillna(False).to_numpy(bool), index=cand.index)
        flagged_cand = flagged_cand & ~recent
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


def allocation_ceiling_breach(
    projects: pd.DataFrame,
    mp_allocation: pd.DataFrame,
    tolerance: float = ALLOCATION_TOLERANCE,
    exclude_from_total=None,
) -> pd.DataFrame:
    """Flag the projects that PUSH an MP's committed total past their OFFICIAL allocation ceiling.

    Each MP's projects are ordered by date (completion date, else recommendation date; ties
    by id; undated last) and a running cumulative total is kept. A project is flagged when the
    cumulative total *including it* exceeds the ceiling by more than `tolerance` -- i.e. the
    project that crosses the line and any later ones that add to the excess. The MP's earlier
    portfolio, committed while still within the ceiling, is NOT flagged.

    A direct comparison against an authoritative figure -- no peer groups, no z-scores.
    MPs are linked to the official rows with `names.match_mps` (normalise both sides,
    then same-state fuzzy for the remainder). An MP with no match, or whose official
    ceiling is unpublished, is NOT APPLICABLE (never treated as a zero ceiling).

    `exclude_from_total`: optional boolean array (positional, same length as
    `projects`) of rows to leave out of the running total (and never flag). The synthetic-data
    pipeline uses it so injected fixtures (test scaffolding, not real commitments) don't push
    MPs over their ceiling.

    Returns a frame indexed by project id: flagged, reason, total_amount (MP total),
    official_ceiling, ceiling_utilization (MP total / ceiling; feeds the ML feature matrix),
    excess_pct (MP total over ceiling), cumulative_amount (running total after this project),
    match_method.
    """
    df = projects.reset_index(drop=True).copy()
    alloc = mp_allocation.copy()
    alloc["official_allocated_ceiling"] = pd.to_numeric(alloc["official_allocated_ceiling"], errors="coerce")

    m = match_mps(df[["mp_name", "state"]], alloc)
    df = df.merge(m[["mp_name", "state", "alloc_index", "method"]], on=["mp_name", "state"], how="left")

    counted = _amount(df).fillna(0.0)
    if exclude_from_total is not None:
        counted = counted.where(~np.asarray(exclude_from_total, dtype=bool), 0.0)
    # total per OFFICIAL MP (so two spellings of one MP are summed together)
    totals = counted.groupby(df["alloc_index"]).transform("sum")
    ceiling = df["alloc_index"].map(alloc["official_allocated_ceiling"])
    utilization = totals / ceiling.replace(0, np.nan)
    excess = utilization - 1

    # running total in date order, per official MP
    when = pd.to_datetime(
        df["completion_date"].where(df["completion_date"].notna(), df.get("recommendation_date")),
        errors="coerce",
    ) if "completion_date" in df.columns else pd.Series(pd.NaT, index=df.index)
    tie = df["id"] if "id" in df.columns else pd.Series(np.arange(len(df)), index=df.index)
    order = (
        pd.DataFrame({"a": df["alloc_index"], "d": when, "t": tie, "amt": counted})
        .dropna(subset=["a"])
        .sort_values(["a", "d", "t"], na_position="last", kind="mergesort")
    )
    cum = order.groupby("a")["amt"].cumsum().reindex(df.index)
    threshold = ceiling * (1 + tolerance)
    flagged = ((cum > threshold) & (counted > 0)).fillna(False)

    reason = pd.Series([None] * len(df), dtype=object)
    for i in df.index[flagged.to_numpy()]:
        over = cum.at[i] / ceiling.at[i] - 1
        reason.at[i] = (
            f"Committing this work takes the MP's running total to ₹{cum.at[i]:,.0f}, "
            f"{over * 100:.1f}% over their official allocation ceiling of ₹{ceiling.at[i]:,.0f}"
        )
    out = pd.DataFrame({
        "flagged": flagged.to_numpy(), "reason": reason.to_numpy(),
        "total_amount": totals.to_numpy(), "official_ceiling": ceiling.to_numpy(),
        "ceiling_utilization": utilization.to_numpy(), "excess_pct": (excess * 100).to_numpy(),
        "cumulative_amount": cum.to_numpy(),
        "match_method": df["method"].to_numpy(),
    })
    out.index = df["id"].to_numpy() if "id" in df.columns else df.index
    out.index.name = "project_id"
    return out


# --- duplicate work -------------------------------------------------------- #
# Generic work-verbs / connectors / administrative words. A match must not be driven by any of
# these -- they are stripped BEFORE comparing, so only the specific part of a description
# (the asset, the place, the identifier) is left to be compared.
_GENERIC_PHRASES = re.compile(
    r"\b(?:supply,? (?:and|&) (?:installation|fixing|erection|laying)|"
    r"supply,? installation (?:and|&) commissioning|providing (?:and|&) (?:fixing|laying|fitting)|"
    r"repairs? (?:and|&) (?:renovation|maintenance)|construction work|constructions?|const\.?|"
    r"installation work|installation|renovation|repair|maintenance|improvement|development|"
    r"upgradation|strengthening|extension|erection|laying|providing|provision|purchase|"
    r"procurement|establishment|setting up|works?|under mplads?|mplads?)\b"
)
_STOPWORDS = frozenset(
    "of the a an and or at in on near from to by with for under within along around towards nearby "
    "as per side is are be via having including incl etc new proposed various different some "
    "village vill gram gaon panchayat gp block tehsil tahsil taluka taluk mandal district dist "
    "ward no nos number nirman karya kary hetu ka ki ke mein me se par".split()
)
_LEADING_SERIAL = re.compile(r"^\s*\d+\s*[-.):]\s*")
_PUNCT = re.compile(r"[^a-z0-9 ]+")


def specific_text(description: object) -> str:
    """Boilerplate-stripped description used for duplicate matching."""
    s = _LEADING_SERIAL.sub("", str(description or "").lower())
    s = _PUNCT.sub(" ", s)
    s = _GENERIC_PHRASES.sub(" ", s)
    return " ".join(t for t in s.split() if t not in _STOPWORDS)


def _is_numeric_token(t: str) -> bool:
    return any(c.isdigit() for c in t)


def duplicate_work(
    projects: pd.DataFrame,
    similarity: int = DUPLICATE_TEXT_SIMILARITY,
    amount_tolerance: float = DUPLICATE_AMOUNT_TOLERANCE,
    min_gap_days: int = DUPLICATE_MIN_GAP_DAYS,
) -> pd.DataFrame:
    """'Same work claimed twice': within one MP + constituency, two projects whose
    descriptions are near-identical, whose amounts are within `amount_tolerance`, AND whose
    dates are at least `min_gap_days` apart. All three must hold.

    Guards against false positives:
      * boilerplate is removed before comparing: generic work-verbs/connectors by phrase
        list, then any word that is common across the whole corpus ("road", "light",
        "school"...) by document frequency. Only RARE tokens (the asset/place identifiers)
        are compared, and >= DUPLICATE_MIN_RARE_TOKENS must remain;
      * numeric tokens must agree exactly (series "Sl. No. 1-150" vs "151-300" are two works);
      * token_sort_ratio, so extra words LOWER the score (token_set would not);
      * a pair sharing the same Work ID is lifecycle continuity, not a duplicate;
      * entries < `min_gap_days` apart are multi-unit purchases entered together.

    Returns a frame indexed by project id: flagged, reason, max_similarity (best text
    similarity to another same-MP work on rare tokens, whatever its amount/date -- the raw
    signal for the ML feature matrix), n_matches.
    """
    df = projects.reset_index(drop=True).copy()
    n_all = len(df)
    flagged = np.zeros(n_all, bool)
    max_sim = np.zeros(n_all)
    n_match = np.zeros(n_all, int)
    reason = np.full(n_all, None, dtype=object)

    toks = df["work_description"].map(lambda d: specific_text(d).split())
    df_count = Counter(t for ts in toks for t in set(ts))
    common_cut = max(DUPLICATE_COMMON_DF * n_all, DUPLICATE_COMMON_DF_FLOOR)
    rare = toks.map(lambda ts: [t for t in ts if df_count[t] <= common_cut and not _is_numeric_token(t)])
    rare_txt = rare.map(" ".join)
    nums = toks.map(lambda ts: " ".join(sorted({t for t in ts if _is_numeric_token(t)})))
    specific_ok = (rare.map(len) >= DUPLICATE_MIN_RARE_TOKENS).to_numpy()

    amount = _amount(df).to_numpy(dtype=float)
    ext = df["external_id"] if "external_id" in df.columns else pd.Series([None] * n_all)
    date = pd.to_datetime(
        df["completion_date"].where(df["completion_date"].notna(), df.get("recommendation_date")),
        errors="coerce",
    )
    day = (date.astype("int64").where(date.notna(), np.nan) / 86_400e9).to_numpy(dtype=float)

    key = (df["mp_name"].map(normalize_mp_name) + "|" + df["constituency"].fillna("").map(_norm)).to_numpy()
    for _, idx in pd.Series(np.arange(n_all)).groupby(key).groups.items():
        idx = np.asarray(idx)
        if len(idx) < 2 or specific_ok[idx].sum() < 2:
            continue
        texts = rare_txt.iloc[idx].tolist()
        # 60 = floor for the ML feature; scores below it are recorded as 0
        S = process.cdist(texts, texts, scorer=fuzz.token_sort_ratio, score_cutoff=60,
                          dtype=np.uint8, workers=-1).astype(np.int16)
        codes = pd.factorize(ext.iloc[idx])[0].astype(np.int64)
        codes = np.where(codes < 0, -(np.arange(len(idx)) + 1), codes)   # null id != any other
        nc = pd.factorize(nums.iloc[idx])[0]
        ok = specific_ok[idx]
        pair_ok = (ok[:, None] & ok[None, :] & (codes[:, None] != codes[None, :])
                   & (nc[:, None] == nc[None, :]))
        a = amount[idx]
        amt_ok = np.abs(a[:, None] - a[None, :]) <= amount_tolerance * np.maximum(a[:, None], a[None, :])
        d = day[idx]
        gap_ok = np.abs(d[:, None] - d[None, :]) >= min_gap_days      # NaN date -> False
        S = np.where(pair_ok, S, 0)
        M = (S >= similarity) & amt_ok & gap_ok
        max_sim[idx] = S.max(axis=1)
        hit = M.any(axis=1)
        flagged[idx] = hit
        n_match[idx] = M.sum(axis=1)
        for local in np.flatnonzero(hit):
            j = int(np.argmax(np.where(M[local], S[local], -1)))
            dj = date.iloc[idx[j]]
            when = dj.strftime("%d %b %Y") if pd.notna(dj) else "another date"
            reason[idx[local]] = (
                f"Near-identical work also recorded for this MP on {when} "
                f"(similarity {int(S[local, j])}%, amounts within {int(amount_tolerance * 100)}%)"
            )

    out = pd.DataFrame({"flagged": flagged, "reason": reason, "max_similarity": max_sim,
                        "n_matches": n_match})
    out.index = df["id"].to_numpy() if "id" in df.columns else df.index
    out.index.name = "project_id"
    return out


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
