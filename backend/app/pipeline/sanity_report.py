"""Post-ingestion sanity report.

Prints record counts, clean-vs-synthetic samples and basic distribution stats,
and writes the same to data/processed/sanity_report.md.

    docker compose exec backend python -m app.pipeline.sanity_report
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

from app.config import settings
from app.database import engine
from app.pipeline.features import add_project_features


def _q(sql: str) -> pd.DataFrame:
    return pd.read_sql(sql, engine)


def build_report() -> str:
    out = io.StringIO()

    def w(line: str = "") -> None:
        out.write(line + "\n")

    proj = _q("SELECT * FROM projects ORDER BY id")
    vtx = _q("SELECT * FROM vendor_transactions ORDER BY id")
    mps = _q("SELECT * FROM mp_summary ORDER BY id")

    w("# MPLAD ingestion — sanity report\n")
    w(f"_snapshot: {settings.database_url.split('@')[-1]}_\n")

    # ---- counts ----
    w("## Record counts\n")
    w(f"- **projects**: {len(proj):,}")
    w(f"  - by status: {proj['status'].value_counts().to_dict()}")
    w(f"  - by source_file: {proj['source_file'].value_counts().to_dict()}")
    real = proj[~proj["is_synthetic_anomaly"]]
    syn = proj[proj["is_synthetic_anomaly"]]
    w(f"  - real: {len(real):,}  |  synthetic: {len(syn):,}")
    if len(syn):
        w(f"  - synthetic by type: {syn['anomaly_type'].value_counts().to_dict()}")
    w(f"- **vendor_transactions**: {len(vtx):,}")
    w(f"  - by payment_status: {vtx['payment_status'].value_counts().to_dict()}")
    vsyn = vtx[vtx["is_synthetic_anomaly"]]
    w(f"  - real: {len(vtx) - len(vsyn):,}  |  synthetic: {len(vsyn):,}")
    if len(vsyn):
        w(f"  - synthetic by type: {vsyn['anomaly_type'].value_counts().to_dict()}")
    w(f"- **mp_summary**: {len(mps):,}")
    w("")

    # ---- amount stats ----
    w("## Amount distributions (real rows only)\n")

    def stats(s: pd.Series) -> str:
        s = pd.to_numeric(s, errors="coerce").dropna()
        if s.empty:
            return "no data"
        return (
            f"n={len(s):,}  min={s.min():,.0f}  median={s.median():,.0f}  "
            f"mean={s.mean():,.0f}  p95={s.quantile(0.95):,.0f}  max={s.max():,.0f}"
        )

    w(f"- sanctioned_amount (recommended): {stats(real['sanctioned_amount'])}")
    w(f"- final_amount (completed):        {stats(real['final_amount'])}")
    w(f"- vendor txn amount:               {stats(vtx[~vtx['is_synthetic_anomaly']]['amount'])}")
    w("")

    # ---- derived category ----
    w("## derived_category distribution\n")
    dc = proj["derived_category"].value_counts()
    for k, v in dc.items():
        w(f"- {k}: {v:,} ({v / len(proj):.1%})")
    w("")

    # ---- district parse / house ----
    w("## Coverage\n")
    w(f"- district parsed (projects): {proj['district'].notna().mean():.1%}")
    w(f"- district parsed (vendor_transactions): {vtx['district'].notna().mean():.1%}")
    w(f"- Rajya Sabha projects: {int(proj['is_rajya_sabha'].sum()):,}")
    w(f"- projects with images: {proj['has_images'].astype('boolean').fillna(False).mean():.1%}")
    w(f"- completed works with a rating: {real[real['status'] == 'completed']['average_rating'].notna().mean():.1%}")
    w("")

    # ---- feature sanity ----
    w("## Engineered-feature sanity (add_project_features on all rows)\n")
    feat = add_project_features(proj)
    for col in ["amount", "amount_z", "amount_ratio_to_median", "days_since_recommendation"]:
        s = pd.to_numeric(feat[col], errors="coerce").dropna()
        w(f"- {col}: min={s.min():,.2f} median={s.median():,.2f} max={s.max():,.2f}")
    # do synthetic cost-inflation rows actually look extreme?
    if len(syn):
        ci = feat[feat["anomaly_type"] == "cost_inflation"]["amount_z"]
        rr = feat[~feat["is_synthetic_anomaly"]]["amount_z"]
        if len(ci):
            w(f"- amount_z — real median {rr.median():.2f} vs cost_inflation median {ci.median():.2f}")
    w("")

    # ---- samples ----
    w("## Sample — real projects\n")
    cols = ["id", "status", "state", "district", "derived_category",
            "sanctioned_amount", "final_amount", "mp_name"]
    w("```")
    w(real[cols].head(5).to_string(index=False))
    w("```\n")
    if len(syn):
        w("## Sample — synthetic anomaly projects (internal labels shown)\n")
        w("```")
        w(syn[cols + ["anomaly_type"]].head(5).to_string(index=False))
        w("```\n")

    return out.getvalue()


def main() -> int:
    report = build_report()
    print(report)
    dest = Path(settings.data_dir).resolve() / "processed" / "sanity_report.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(report, encoding="utf-8")
    print(f"\nwritten -> {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
