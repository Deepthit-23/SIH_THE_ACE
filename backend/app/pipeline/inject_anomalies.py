"""Synthetic anomaly injector.

None of the real MPLAD data is labelled as fraud, so we append a small set of
synthetic rows with realistic-but-extreme patterns and tag them
`is_synthetic_anomaly = True` / `anomaly_type = <kind>`. These labels are used
ONLY for precision/recall validation of the rule engine and ML model -- they are
never exposed through the API or UI.

Value ranges are derived from the actual distributions already in the DB, not
picked arbitrarily.

    docker compose exec backend python -m app.pipeline.inject_anomalies --clear
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from datetime import timedelta

import numpy as np
import pandas as pd
from sqlalchemy import text

from app.database import engine
from app.pipeline import SNAPSHOT_DATE, rules
from app.pipeline.names import match_mps

PROJECT_COLS = [
    "external_id", "source_file", "work_description", "category", "derived_category",
    "mp_name", "constituency", "state", "house", "is_rajya_sabha", "ida", "district",
    "sanctioned_amount", "final_amount", "spent_amount", "contractor_name",
    "start_date", "recommendation_date", "completion_date", "status", "has_images",
    "average_rating", "is_synthetic_anomaly", "anomaly_type",
]
VTX_COLS = [
    "mp_name", "constituency", "state", "house", "work_description", "vendor", "ida",
    "district", "amount", "expenditure_date", "payment_status",
    "is_synthetic_anomaly", "anomaly_type",
]


def make_id_pool(real_ids: set[int], rng: np.random.Generator) -> Iterator[str]:
    """Yield unique numeric Work-ID strings in the real ID range, never colliding
    with a real ID or a previously issued synthetic one.

    Synthetic rows must be indistinguishable from real rows by any field other
    than the internal-only `is_synthetic_anomaly` / `anomaly_type` markers.
    """
    lo, hi = min(real_ids), max(real_ids)
    issued: set[int] = set(real_ids)
    while True:
        cand = int(rng.integers(lo, hi + 1))
        if cand in issued:
            continue
        issued.add(cand)
        yield str(cand)


# --------------------------------------------------------------------------- #
def inject_cost_inflation(
    real: pd.DataFrame, rng: np.random.Generator, n: int, id_pool: Iterator[str]
) -> pd.DataFrame:
    """Clone real works, scale the amount 3-10x above their peer-group median."""
    real = real.copy()
    real["amount"] = pd.to_numeric(real["sanctioned_amount"], errors="coerce").fillna(
        pd.to_numeric(real["final_amount"], errors="coerce")
    )
    med = real.groupby([real["state"].fillna("?"), real["derived_category"].fillna("other")])[
        "amount"
    ].median()
    overall_med = real["amount"].median()

    picks = real.sample(n=min(n, len(real)), random_state=int(rng.integers(1e9))).reset_index(drop=True)
    rows = []
    for _, r in picks.iterrows():
        base = med.get((r["state"] or "?", r["derived_category"] or "other"), overall_med)
        base = max(float(base or overall_med), float(r["amount"] or overall_med), 50_000.0)
        factor = float(rng.uniform(3.0, 10.0))
        amount = round(base * factor, 2)
        is_completed = r["status"] == "completed"
        rows.append({
            "external_id": next(id_pool),
            "source_file": r["source_file"],
            "work_description": r["work_description"],
            "category": r["category"],
            "derived_category": r["derived_category"],
            "mp_name": r["mp_name"], "constituency": r["constituency"],
            "state": r["state"], "house": r["house"],
            "is_rajya_sabha": bool(r["is_rajya_sabha"]),
            "ida": r["ida"], "district": r["district"],
            "sanctioned_amount": None if is_completed else amount,
            "final_amount": amount if is_completed else None,
            "spent_amount": None, "contractor_name": None,
            "start_date": None,
            "recommendation_date": None if is_completed else r["recommendation_date"],
            "completion_date": r["completion_date"] if is_completed else None,
            "status": r["status"],
            "has_images": r["has_images"], "average_rating": None,
            "is_synthetic_anomaly": True, "anomaly_type": "cost_inflation",
        })
    return pd.DataFrame(rows, columns=PROJECT_COLS)


def inject_stalled_projects(
    real: pd.DataFrame, rng: np.random.Generator, n: int, id_pool: Iterator[str],
    low_delivery_units: set[tuple[str, str]] | None = None,
) -> pd.DataFrame:
    """Recommended works with an old recommendation date and no follow-through.

    Sampled from MPs that broadly under-deliver (completion_rate below the median),
    so the synthetic "ghost project" pattern is internally coherent.
    """
    rec = real[real["status"] == "recommended"]
    if low_delivery_units:
        key = list(zip(rec["mp_name"], rec["constituency"]))
        rec_ld = rec[pd.Series([k in low_delivery_units for k in key], index=rec.index)]
        rec = rec_ld if len(rec_ld) >= n else rec
    src = rec if len(rec) else real
    picks = src.sample(n=min(n, len(src)), random_state=int(rng.integers(1e9))).reset_index(drop=True)
    amt = pd.to_numeric(real["sanctioned_amount"], errors="coerce").dropna()
    lo, hi = float(amt.quantile(0.25)), float(amt.quantile(0.85))
    rows = []
    for _, r in picks.iterrows():
        age = int(rng.integers(400, 1001))
        rows.append({
            "external_id": next(id_pool), "source_file": "recommended_works",
            "work_description": r["work_description"], "category": r["category"],
            "derived_category": r["derived_category"],
            "mp_name": r["mp_name"], "constituency": r["constituency"],
            "state": r["state"], "house": r["house"],
            "is_rajya_sabha": bool(r["is_rajya_sabha"]),
            "ida": r["ida"], "district": r["district"],
            "sanctioned_amount": round(float(rng.uniform(lo, hi)), 2),
            "final_amount": None, "spent_amount": None, "contractor_name": None,
            "start_date": None,
            "recommendation_date": SNAPSHOT_DATE - timedelta(days=age),
            "completion_date": None, "status": "recommended",
            "has_images": False, "average_rating": None,
            "is_synthetic_anomaly": True, "anomaly_type": "stalled_project",
        })
    return pd.DataFrame(rows, columns=PROJECT_COLS)


def inject_contractor_concentration(
    vtx: pd.DataFrame, rng: np.random.Generator, n_units: int
) -> pd.DataFrame:
    """Invent a vendor that captures an implausible share of an MP's spend."""
    units = (
        vtx.dropna(subset=["mp_name", "constituency"])
        .groupby(["mp_name", "constituency", "state", "house"])
        .size()
        .reset_index(name="cnt")
    )
    units = units[units["cnt"].between(10, 80)]
    picks = units.sample(n=min(n_units, len(units)), random_state=int(rng.integers(1e9)))
    amt = pd.to_numeric(vtx["amount"], errors="coerce").dropna()
    lo, hi = float(amt.quantile(0.55)), float(amt.quantile(0.95))
    # Plausible-looking company names -- the synthetic marker is is_synthetic_anomaly,
    # never the vendor string (which shows in the UI).
    ring_names = [
        "APEX INFRA SOLUTIONS PVT LTD", "SHREE BALAJI CONSTRUCTIONS",
        "NAVKAR ENTERPRISES", "R K INFRAPROJECTS PVT LTD",
        "SUNRISE BUILDCON", "MAA VAISHNO CONSTRUCTION CO",
        "GALAXY ENGINEERING WORKS", "PRIME CIVIL CONTRACTORS PVT LTD",
        "SIDDHIVINAYAK INFRATECH", "NEW BHARAT CONSTRUCTIONS",
    ]
    rows = []
    for i, u in enumerate(picks.itertuples(index=False)):
        vendor = ring_names[i % len(ring_names)]
        # ~1.8x the MP's existing txns -> the ring vendor ends up holding ~65%.
        ring = max(25, int(u.cnt * 1.8))
        for _ in range(ring):
            rows.append({
                "mp_name": u.mp_name, "constituency": u.constituency,
                "state": u.state, "house": u.house,
                "work_description": "Construction of CC road with side drain",
                "vendor": vendor, "ida": None, "district": None,
                "amount": round(float(rng.uniform(lo, hi)), 2),
                "expenditure_date": SNAPSHOT_DATE - timedelta(days=int(rng.integers(1, 330))),
                "payment_status": "Payment Success",
                "is_synthetic_anomaly": True, "anomaly_type": "contractor_concentration",
            })
    return pd.DataFrame(rows, columns=VTX_COLS)


def inject_payment_gap(vtx: pd.DataFrame, rng: np.random.Generator, n_units: int) -> pd.DataFrame:
    """Burst of large 'Payment In-Progress' transactions for a few MPs."""
    units = (
        vtx.dropna(subset=["mp_name", "constituency"])
        .groupby(["mp_name", "constituency", "state", "house"]).size().reset_index(name="cnt")
    )
    units = units[units["cnt"] >= 20]
    picks = units.sample(n=min(n_units, len(units)), random_state=int(rng.integers(1e9)))
    amt = pd.to_numeric(vtx["amount"], errors="coerce").dropna()
    lo, hi = float(amt.quantile(0.8)), float(amt.quantile(0.99))
    pg_names = [
        "UNITY CONSTRUCTION CO", "SHIVAM ENTERPRISES", "TIRUPATI BUILDERS",
        "M/S ANJANI INFRA", "GREENFIELD CONTRACTORS PVT LTD",
    ]
    rows = []
    for u in picks.itertuples(index=False):
        # ~0.9x the MP's existing txns, at high value -> in-progress value share > 40%.
        for _ in range(max(25, int(u.cnt * 0.9))):
            rows.append({
                "mp_name": u.mp_name, "constituency": u.constituency,
                "state": u.state, "house": u.house,
                "work_description": "Construction and repair of roads and drains",
                "vendor": pg_names[int(rng.integers(0, len(pg_names)))], "ida": None, "district": None,
                "amount": round(float(rng.uniform(lo, hi)), 2),
                "expenditure_date": SNAPSHOT_DATE - timedelta(days=int(rng.integers(1, 120))),
                "payment_status": "Payment In-Progress",
                "is_synthetic_anomaly": True, "anomaly_type": "payment_gap",
            })
    return pd.DataFrame(rows, columns=VTX_COLS)


def _project_row(src: pd.Series, kind: str, id_pool: Iterator[str], amount: float, status: str,
                 description: str, when) -> dict:
    """One synthetic project row cloned from `src`'s MP/place, with its own amount/date."""
    done = status == "completed"
    return {
        "external_id": next(id_pool),
        "source_file": "completed_works" if done else "recommended_works",
        "work_description": description, "category": src["category"],
        "derived_category": src["derived_category"],
        "mp_name": src["mp_name"], "constituency": src["constituency"],
        "state": src["state"], "house": src["house"],
        "is_rajya_sabha": bool(src["is_rajya_sabha"]),
        "ida": src["ida"], "district": src["district"],
        "sanctioned_amount": None if done else round(amount, 2),
        "final_amount": round(amount, 2) if done else None,
        "spent_amount": None, "contractor_name": None, "start_date": None,
        "recommendation_date": None if done else when,
        "completion_date": when if done else None,
        "status": status, "has_images": False, "average_rating": None,
        "is_synthetic_anomaly": True, "anomaly_type": kind,
    }


def inject_allocation_breach(
    real: pd.DataFrame, alloc: pd.DataFrame, rng: np.random.Generator, n_mps: int,
    id_pool: Iterator[str], works_per_mp: int = 8,
) -> pd.DataFrame:
    """Dedicated breach fixtures: pick MPs whose REAL committed total is 70-95% of their
    official ceiling and add works that push the total 5-25% OVER it.

    The added works are small, recent 'recommended' entries built from other MPs' real
    descriptions in the same state, so no other rule (stalled, duplicate) is provoked.
    Cost-inflation fixtures are never used for this -- they are excluded from the ceiling total.
    """
    amt = rules._amount(real).fillna(0.0)
    pairs = real[["mp_name", "state"]].drop_duplicates()
    m = match_mps(pairs, alloc)
    m = m[m["alloc_index"].notna()]
    key = dict(zip(zip(m["mp_name"], m["state"]), m["alloc_index"]))
    real = real.assign(_alloc=[key.get(k) for k in zip(real["mp_name"], real["state"])], _amt=amt)
    tot = real.groupby("_alloc")["_amt"].sum()
    ceil = tot.index.map(alloc["official_allocated_ceiling"])
    util = pd.Series(tot.to_numpy() / pd.to_numeric(pd.Series(ceil), errors="coerce").to_numpy(), index=tot.index)
    cand = util[(util >= 0.70) & (util <= 0.95)].index.to_numpy()
    picks = rng.choice(cand, size=min(n_mps, len(cand)), replace=False)

    rows = []
    for a in picks:
        ceiling = float(alloc.at[a, "official_allocated_ceiling"])
        target = float(rng.uniform(1.05, 1.25))
        excess = target * ceiling - float(tot[a])
        mine = real[real["_alloc"] == a]
        host = mine.iloc[0]
        pool = real[(real["state"] == host["state"]) & (real["mp_name"] != host["mp_name"])
                    & real["work_description"].notna()]
        descs = pool["work_description"].sample(n=works_per_mp, random_state=int(rng.integers(1e9))).tolist()
        w = rng.dirichlet(np.ones(works_per_mp) * 4)
        for d, share in zip(descs, w):
            when = SNAPSHOT_DATE - timedelta(days=int(rng.integers(20, 200)))
            rows.append(_project_row(host, "allocation_ceiling_breach", id_pool, excess * share,
                                     "recommended", d, when))
    return pd.DataFrame(rows, columns=PROJECT_COLS)


def inject_duplicate_work(
    real: pd.DataFrame, rng: np.random.Generator, n: int, id_pool: Iterator[str],
) -> pd.DataFrame:
    """Re-claim a real work: same MP + constituency, near-identical description (tiny wording
    edit), amount within +/-8%, a different date 60-300 days away, a new Work ID.

    Sources are real works that carry a distinctive description (>= 4 specific tokens) and are
    not already duplicate-flagged, so the fixture tests the rule rather than template noise.
    """
    already = rules.duplicate_work(real)["flagged"]
    amt = rules._amount(real)
    spec_len = real["work_description"].map(lambda d: len(rules.specific_text(d).split()))
    ok = (~already.to_numpy()) & (spec_len.to_numpy() >= 4) & (amt.between(50_000, 3_000_000)).to_numpy()
    src = real[ok].sample(n=min(n, int(ok.sum())), random_state=int(rng.integers(1e9)))
    rows = []
    for _, r in src.iterrows():
        a = float(pd.to_numeric(r["sanctioned_amount"], errors="coerce")
                  if pd.notna(r["sanctioned_amount"]) else r["final_amount"])
        new_amt = a * float(rng.uniform(0.92, 1.08))
        done = r["status"] == "completed"
        base = pd.Timestamp(r["completion_date"] if done else r["recommendation_date"])
        shift = timedelta(days=int(rng.integers(60, 301)))
        when = base + shift if base + shift <= pd.Timestamp(SNAPSHOT_DATE) else base - shift
        d = str(r["work_description"]).strip()
        words = d.split()
        d = " ".join(words[:-1]) if len(words) > 6 and rng.random() < 0.5 else d.upper() if rng.random() < 0.5 else d + " ."
        rows.append(_project_row(r, "duplicate_work", id_pool, new_amt,
                                 "completed" if done else "recommended", d, when.date()))
    return pd.DataFrame(rows, columns=PROJECT_COLS)


# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--clear", action="store_true", help="delete existing synthetic rows first")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--cost-inflation", type=int, default=250)
    p.add_argument("--stalled", type=int, default=150)
    p.add_argument("--contractor-units", type=int, default=8)
    p.add_argument("--payment-gap-units", type=int, default=6)
    p.add_argument("--ceiling-mps", type=int, default=12)
    p.add_argument("--duplicates", type=int, default=120)
    args = p.parse_args(argv)

    rng = np.random.default_rng(args.seed)

    if args.clear:
        with engine.begin() as c:
            d1 = c.execute(text("DELETE FROM projects WHERE is_synthetic_anomaly")).rowcount
            d2 = c.execute(text("DELETE FROM vendor_transactions WHERE is_synthetic_anomaly")).rowcount
        print(f"cleared {d1} project + {d2} vendor synthetic rows")

    real_proj = pd.read_sql(
        "SELECT * FROM projects WHERE is_synthetic_anomaly = false", engine
    )
    real_vtx = pd.read_sql(
        "SELECT * FROM vendor_transactions WHERE is_synthetic_anomaly = false", engine
    )
    if real_proj.empty or real_vtx.empty:
        print("ERROR: no real data found. Run prepare_data first.")
        return 1

    real_ids = set(
        pd.to_numeric(real_proj["external_id"], errors="coerce").dropna().astype("int64")
    )
    if not real_ids:
        print("ERROR: no numeric real Work IDs found to derive a synthetic ID range.")
        return 1
    id_pool = make_id_pool(real_ids, rng)
    print(
        f"synthetic Work IDs: numeric, drawn from real range "
        f"[{min(real_ids):,} .. {max(real_ids):,}], {len(real_ids):,} real IDs excluded"
    )

    alloc = pd.read_sql("SELECT * FROM mp_allocation ORDER BY id", engine)
    if alloc.empty:
        print("ERROR: mp_allocation is empty. Run app.pipeline.allocation_ingest first.")
        return 1

    mp_sum = pd.read_sql(
        "SELECT mp_name, constituency, completion_rate_pct FROM mp_summary", engine
    )
    cutoff = min(30.0, float(mp_sum["completion_rate_pct"].median()))
    low_delivery_units = {
        (r.mp_name, r.constituency)
        for r in mp_sum[mp_sum["completion_rate_pct"] < cutoff].itertuples(index=False)
    }
    print(f"stalled-project source: {len(low_delivery_units)} MP-units with completion_rate < {cutoff:.0f}%")

    batches = [
        ("projects", inject_cost_inflation(real_proj, rng, args.cost_inflation, id_pool)),
        ("projects", inject_stalled_projects(
            real_proj, rng, args.stalled, id_pool, low_delivery_units)),
        ("vendor_transactions", inject_contractor_concentration(real_vtx, rng, args.contractor_units)),
        ("vendor_transactions", inject_payment_gap(real_vtx, rng, args.payment_gap_units)),
        ("projects", inject_allocation_breach(
            real_proj, alloc, rng, args.ceiling_mps, id_pool)),
        ("projects", inject_duplicate_work(real_proj, rng, args.duplicates, id_pool)),
    ]
    for table, df in batches:
        df = df.astype(object).where(pd.notna(df), None)
        df.to_sql(table, engine, if_exists="append", index=False, chunksize=500, method="multi")
        kinds = df["anomaly_type"].value_counts().to_dict()
        print(f"  +{len(df):>5} -> {table}   {kinds}")

    # synthetic rows clone real rows' state/district, so they resolve through the same pairs
    from app.pipeline import location
    location.apply_to_db(engine)

    dup = pd.read_sql(
        """
        SELECT external_id, count(*) FILTER (WHERE is_synthetic_anomaly) AS syn,
               count(*) FILTER (WHERE NOT is_synthetic_anomaly) AS real
        FROM projects WHERE external_id IS NOT NULL
        GROUP BY external_id HAVING count(*) FILTER (WHERE is_synthetic_anomaly) > 0
             AND count(*) FILTER (WHERE NOT is_synthetic_anomaly) > 0
        """,
        engine,
    )
    if not dup.empty:
        print(f"WARNING: {len(dup)} synthetic Work IDs collide with a real ID!")
        return 1
    print("id-collision check: OK (0 synthetic Work IDs overlap a real one)")

    print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
