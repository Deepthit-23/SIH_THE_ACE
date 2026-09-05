"""End-to-end scoring pipeline: run rules + ML, combine, populate `risk_flags`.

    docker compose exec backend python -m app.pipeline.score_projects
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import delete, insert, inspect

from app import audit
from app.database import engine
from app.models import AuditLog, RiskFlag
from app.pipeline import ml_model, risk_scorer, rules


def _ensure_audit_schema() -> None:
    """audit_log gained `project_id`/`payload` in Phase 6; recreate if on old schema."""
    insp = inspect(engine)
    if "audit_log" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("audit_log")}
        if not {"project_id", "payload"} <= cols:
            AuditLog.__table__.drop(engine)
    AuditLog.__table__.create(engine, checkfirst=True)


def load() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    # ORDER BY id: the IsolationForest subsamples by row position, so a stable
    # row order is required for reproducible scores across fresh DB loads.
    proj = pd.read_sql("SELECT * FROM projects ORDER BY id", engine)
    vtx = pd.read_sql("SELECT * FROM vendor_transactions ORDER BY id", engine)
    mps = pd.read_sql("SELECT * FROM mp_summary ORDER BY id", engine)
    return proj, vtx, mps


def run(contamination: float = 0.04) -> pd.DataFrame:
    proj, vtx, mps = load()
    print(f"projects={len(proj):,} vendor_txns={len(vtx):,} mp_summary={len(mps):,}")

    # --- rule engine ---
    cost = rules.cost_anomaly(proj)
    stalled = rules.stalled_project(proj, vtx, mps)
    contractor = rules.contractor_concentration(vtx)
    payment = rules.payment_gap(vtx, mps)
    print(
        f"rules: cost={int(cost['flagged'].sum())} "
        f"stalled={int(stalled['flagged'].sum())} "
        f"contractor(groups)={int(contractor['flagged'].sum())} "
        f"payment(groups)={int(payment['flagged'].sum())}"
    )

    # --- ML detector (independent) ---
    X = ml_model.build_feature_matrix(proj, vtx, mps)
    model = ml_model.train_isolation_forest(X, contamination=contamination)
    ml = ml_model.score(model, X)
    stats = ml_model.population_stats(X)
    # score any project that can contribute (hard flag OR high percentile), so the
    # combiner has fragments for the p>=92 rows too, not just the hard flags.
    explain_idx = ml.index[ml["ml_flag"] | (ml["ml_percentile"] >= 92.0)]
    fragments = ml_model.explain_fragments(X, explain_idx, stats)
    print(f"ml: contamination={contamination} flagged={int(ml['ml_flag'].sum())}")

    # --- combine ---
    combined = risk_scorer.combine(proj, cost, stalled, contractor, payment, ml, ml_fragments=fragments)
    print(
        f"combined_risk_score: min={combined['combined_risk_score'].min():.1f} "
        f"median={combined['combined_risk_score'].median():.1f} "
        f"max={combined['combined_risk_score'].max():.1f} "
        f">=50: {(combined['combined_risk_score'] >= 50).sum():,}  "
        f">=70: {(combined['combined_risk_score'] >= 70).sum():,}"
    )
    return combined


def write_risk_flags(combined: pd.DataFrame) -> tuple[int, int]:
    """Replace risk_flags AND append one hash-chained audit_log entry per row,
    atomically. The chain is never cleared -- it accumulates across re-scorings.
    """
    records = [
        {
            "project_id": int(pid),
            "rule_flags": row["rule_flags"],
            "ml_anomaly_score": None if pd.isna(row["ml_anomaly_score"]) else float(row["ml_anomaly_score"]),
            "combined_risk_score": float(row["combined_risk_score"]),
            "explanation": row["explanation"],
        }
        for pid, row in combined.iterrows()
    ]
    ts = datetime.now(timezone.utc)
    with engine.begin() as conn:
        conn.execute(delete(RiskFlag))
        for i in range(0, len(records), 5000):
            conn.execute(insert(RiskFlag), records[i : i + 5000])
        n_audit = audit.append_entries(
            conn,
            ((r["project_id"], r["combined_risk_score"], r["explanation"], ts) for r in records),
        )
    return len(records), n_audit


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--contamination", type=float, default=0.04)
    p.add_argument("--dry-run", action="store_true", help="score but don't write risk_flags")
    args = p.parse_args(argv)

    combined = run(args.contamination)
    if args.dry_run:
        print("dry run -- risk_flags not written")
        return 0
    _ensure_audit_schema()
    n, n_audit = write_risk_flags(combined)
    print(f"wrote {n:,} risk_flags rows + {n_audit:,} audit_log entries (chain continued)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
