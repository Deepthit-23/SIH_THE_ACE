"""Run all four rules against the full dataset and report recall vs. the
synthetic anomalies + false-positive rate against real rows.

    docker compose exec backend python -m app.pipeline.evaluate_rules
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

from app.config import settings
from app.database import engine
from app.pipeline import rules


def _load() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    proj = pd.read_sql("SELECT * FROM projects ORDER BY id", engine)
    vtx = pd.read_sql("SELECT * FROM vendor_transactions ORDER BY id", engine)
    mps = pd.read_sql("SELECT * FROM mp_summary ORDER BY id", engine)
    return proj, vtx, mps


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def build_report() -> str:
    proj, vtx, mps = _load()
    out = io.StringIO()

    def w(s: str = "") -> None:
        out.write(s + "\n")

    truth = proj.set_index("id")[["is_synthetic_anomaly", "anomaly_type"]]
    truth["is_synthetic_anomaly"] = truth["is_synthetic_anomaly"].astype(bool)

    # ---------------- run rules ----------------
    cost = rules.cost_anomaly(proj).join(truth)
    stalled = rules.stalled_project(proj, vtx, mps).join(truth)
    contractor = rules.contractor_concentration(vtx)
    pay = rules.payment_gap(vtx, mps)

    w("# Rule-engine evaluation\n")
    w(f"_db: {settings.database_url.split('@')[-1]}_\n")
    w(f"thresholds: cost_z={rules.COST_Z_THRESHOLD}, "
      f"contractor_share={rules.CONTRACTOR_SHARE_THRESHOLD}, "
      f"stalled_age_days={rules.STALLED_MIN_AGE_DAYS}, "
      f"payment_share={rules.PAYMENT_INPROGRESS_SHARE_THRESHOLD}\n")

    # ---------------- flag volumes ----------------
    w("## Flags raised\n")
    w(f"- cost_anomaly: {int(cost['flagged'].sum()):,} / {len(cost):,} projects")
    w(f"- stalled_project: {int(stalled['flagged'].sum()):,} / {len(stalled):,} recommended projects")
    w(f"- contractor_concentration: {int(contractor['flagged'].sum()):,} / {len(contractor):,} (MP, vendor, unit) groups")
    w(f"- payment_gap: {int(pay['flagged'].sum()):,} / {len(pay):,} (MP, constituency) groups")
    w("")

    # ---------------- recall by anomaly_type ----------------
    w("## Recall vs. synthetic anomalies\n")
    w("| anomaly_type | grain | population | caught | recall |")
    w("|---|---|--:|--:|--:|")

    def proj_recall(frame: pd.DataFrame, kind: str) -> tuple[int, int]:
        sub = frame[frame["anomaly_type"] == kind]
        return int(sub["flagged"].sum()), len(sub)

    c_hit, c_tot = proj_recall(cost, "cost_inflation")
    s_hit, s_tot = proj_recall(stalled, "stalled_project")
    w(f"| cost_inflation | project | {c_tot} | {c_hit} | {_pct(c_hit / c_tot)} |")
    w(f"| stalled_project | project | {s_tot} | {s_hit} | {_pct(s_hit / s_tot)} |")

    # contractor: a synthetic txn is caught if its (mp, vendor, unit) group is flagged
    vlabel, _ = rules._geo_unit(vtx)
    vpair = list(zip(
        vtx["mp_name"].fillna("?").astype(str),
        vtx["vendor"].fillna("UNKNOWN").astype(str).str.strip(),
        vlabel,
    ))
    vtx = vtx.assign(_pair=vpair)
    fl = contractor[contractor["flagged"]]
    flagged_pairs = set(zip(fl["mp_name"], fl["vendor"], fl["unit"]))
    vtx["_caught"] = vtx["_pair"].isin(flagged_pairs)
    con_syn = vtx[vtx["anomaly_type"] == "contractor_concentration"]
    con_hit, con_tot = int(con_syn["_caught"].sum()), len(con_syn)
    con_groups = set(con_syn["_pair"])
    w(f"| contractor_concentration | vendor txn | {con_tot} | {con_hit} | {_pct(con_hit / con_tot)} |")
    w(f"| &nbsp;&nbsp;↳ distinct vendor groups | (vendor,unit) | {len(con_groups)} | "
      f"{len(con_groups & flagged_pairs)} | {_pct(len(con_groups & flagged_pairs) / len(con_groups))} |")

    # payment gap: caught if the (mp, constituency) group is flagged
    flagged_mp = set(
        zip(pay.loc[pay["flagged"], "mp_name"], pay.loc[pay["flagged"], "constituency"])
    )
    vtx["_mppair"] = list(zip(vtx["mp_name"], vtx["constituency"]))
    vtx["_pg_caught"] = vtx["_mppair"].isin(flagged_mp)
    pg_syn = vtx[vtx["anomaly_type"] == "payment_gap"]
    pg_hit, pg_tot = int(pg_syn["_pg_caught"].sum()), len(pg_syn)
    pg_groups = set(pg_syn["_mppair"])
    w(f"| payment_gap | vendor txn | {pg_tot} | {pg_hit} | {_pct(pg_hit / pg_tot)} |")
    w(f"| &nbsp;&nbsp;↳ distinct MP groups | (mp,constituency) | {len(pg_groups)} | "
      f"{len(pg_groups & flagged_mp)} | {_pct(len(pg_groups & flagged_mp) / len(pg_groups))} |")
    w("")

    proj_caught = c_hit + s_hit
    w(f"**Project-grain synthetic recall: {proj_caught} / {c_tot + s_tot} "
      f"= {_pct(proj_caught / (c_tot + s_tot))}**\n")

    # ---------------- false positives ----------------
    w("## False-positive rate (real, non-synthetic entities)\n")
    w("| rule | real entities | flagged | FP rate |")
    w("|---|--:|--:|--:|")

    real_cost = cost[~cost["is_synthetic_anomaly"].fillna(False)]
    w(f"| cost_anomaly | {len(real_cost):,} projects | {int(real_cost['flagged'].sum()):,} | "
      f"{_pct(real_cost['flagged'].mean())} |")

    real_stall = stalled[~stalled["is_synthetic_anomaly"].fillna(False)]
    w(f"| stalled_project | {len(real_stall):,} recommended | {int(real_stall['flagged'].sum()):,} | "
      f"{_pct(real_stall['flagged'].mean())} |")

    grp_syn = vtx.groupby("_pair")["is_synthetic_anomaly"].any()
    contractor = contractor.assign(
        _syn=list(zip(contractor["mp_name"], contractor["vendor"], contractor["unit"]))
    )
    contractor["_syn"] = contractor["_syn"].map(grp_syn).fillna(False)
    real_con = contractor[~contractor["_syn"]]
    w(f"| contractor_concentration | {len(real_con):,} groups | {int(real_con['flagged'].sum()):,} | "
      f"{_pct(real_con['flagged'].mean())} |")

    grp_syn_pg = vtx.groupby("_mppair")["is_synthetic_anomaly"].any()
    pay = pay.assign(_syn=list(zip(pay["mp_name"], pay["constituency"])))
    pay["_syn"] = pay["_syn"].map(grp_syn_pg).fillna(False)
    real_pay = pay[~pay["_syn"]]
    w(f"| payment_gap | {len(real_pay):,} groups | {int(real_pay['flagged'].sum()):,} | "
      f"{_pct(real_pay['flagged'].mean())} |")
    w("")

    # ---------------- cross-contamination ----------------
    w("## Cross-hits (rule firing on a different anomaly_type)\n")
    for kind in ["stalled_project", "cost_inflation"]:
        n = int(cost[cost["anomaly_type"] == kind]["flagged"].sum())
        w(f"- cost_anomaly fired on {n} `{kind}` rows")
    for kind in ["cost_inflation", "stalled_project"]:
        n = int(stalled[stalled["anomaly_type"] == kind]["flagged"].sum())
        w(f"- stalled_project fired on {n} `{kind}` rows")
    w("")

    # ---------------- sample reasons ----------------
    w("## Sample reasons\n```")
    for frame, col in [(cost, "reason"), (stalled, "reason")]:
        for r in frame.loc[frame["flagged"], col].dropna().head(3):
            w(f"- {r}")
    for r in contractor.loc[contractor["flagged"], "reason"].dropna().head(3):
        w(f"- {r}")
    for r in pay.loc[pay["flagged"], "reason"].dropna().head(3):
        w(f"- {r}")
    w("```")

    return out.getvalue()


def main() -> int:
    report = build_report()
    print(report)
    dest = Path(settings.data_dir).resolve() / "processed" / "rule_eval.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(report, encoding="utf-8")
    print(f"\nwritten -> {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
