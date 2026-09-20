"""Run all six rules against the full dataset and report recall vs. the
synthetic anomalies + false-positive rate against real rows.

    docker compose exec backend python -m app.pipeline.evaluate_rules
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

from app.config import settings
from app.database import engine
import numpy as np

from app.pipeline import rules
from app.pipeline.names import match_mps


def _load() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    alloc = pd.read_sql("SELECT * FROM mp_allocation ORDER BY id", engine)
    proj = pd.read_sql("SELECT * FROM projects ORDER BY id", engine)
    vtx = pd.read_sql("SELECT * FROM vendor_transactions ORDER BY id", engine)
    mps = pd.read_sql("SELECT * FROM mp_summary ORDER BY id", engine)
    return proj, vtx, mps, alloc


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def build_report() -> str:
    proj, vtx, mps, alloc = _load()
    out = io.StringIO()

    def w(s: str = "") -> None:
        out.write(s + "\n")

    truth = proj.set_index("id")[["is_synthetic_anomaly", "anomaly_type"]]
    truth["is_synthetic_anomaly"] = truth["is_synthetic_anomaly"].astype(bool)

    # ---------------- run rules ----------------
    cost = rules.cost_anomaly(proj).join(truth)
    stalled = rules.stalled_project(proj, vtx, mps, mp_allocation=alloc).join(truth)
    contractor = rules.contractor_concentration(vtx)
    pay = rules.payment_gap(vtx, mps)
    # Fixtures other than the breach cases are test scaffolding, not commitments (see score_projects)
    fixture = (truth["is_synthetic_anomaly"] & (truth["anomaly_type"] != "allocation_ceiling_breach")).to_numpy()
    ceiling = rules.allocation_ceiling_breach(proj, alloc, exclude_from_total=fixture).join(truth)
    dup = rules.duplicate_work(proj).join(truth)

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
    w(f"- allocation_ceiling_breach: {int(ceiling['flagged'].sum()):,} / {len(ceiling):,} projects")
    w(f"- duplicate_work: {int(dup['flagged'].sum()):,} / {len(dup):,} projects")
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

    # ceiling / duplicate: project grain, plus MP-unit grain for the ceiling
    pm = match_mps(proj[["mp_name", "state"]], alloc)
    akey = dict(zip(zip(pm["mp_name"], pm["state"]), pm["alloc_index"]))
    proj_alloc = pd.Series([akey.get(k) for k in zip(proj["mp_name"], proj["state"])], index=proj["id"])
    ceiling["_alloc"] = proj_alloc.reindex(ceiling.index).to_numpy()
    ce_hit, ce_tot = proj_recall(ceiling, "allocation_ceiling_breach")
    host_all = set(ceiling.loc[ceiling["anomaly_type"] == "allocation_ceiling_breach", "_alloc"].dropna())
    ce_mps = ceiling[ceiling["_alloc"].isin(host_all)].groupby("_alloc")["flagged"].any()
    # The rule flags the projects that CROSS the ceiling in date order, which for an injected MP may
    # be a real later-dated project rather than an injected one. So the honest recall grain is the MP.
    w(f"| allocation_ceiling_breach (injected rows themselves) | project | {ce_tot} | {ce_hit} | {_pct(ce_hit / ce_tot)} |")
    w(f"| &nbsp;&nbsp;↳ MPs with >=1 flagged project (crossing rows) | MP | {len(ce_mps)} | {int(ce_mps.sum())} | "
      f"{_pct(ce_mps.mean())} |")
    du_hit, du_tot = proj_recall(dup, "duplicate_work")
    w(f"| duplicate_work | project | {du_tot} | {du_hit} | {_pct(du_hit / du_tot)} |")

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

    p_hit, p_tot = c_hit + s_hit + du_hit, c_tot + s_tot + du_tot
    w(f"**Project-grain synthetic recall (cost, stalled, duplicate): {p_hit} / {p_tot} = {_pct(p_hit / p_tot)}**\n")

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

    # Ceiling: real rows of MPs that do NOT host an injected breach (matched to the official rows)
    host = set(ceiling.loc[ceiling["anomaly_type"] == "allocation_ceiling_breach", "_alloc"].dropna())
    real_ce = ceiling[~ceiling["is_synthetic_anomaly"].fillna(False) & ~ceiling["_alloc"].isin(host)]
    appl = real_ce[real_ce["official_ceiling"].notna()]
    mp_fl = appl.groupby("_alloc")["flagged"].any()
    w(f"| allocation_ceiling_breach (row) | {len(appl):,} projects, {len(host)} host MPs excluded | "
      f"{int(appl['flagged'].sum()):,} | {_pct(appl['flagged'].mean())} |")
    w(f"| allocation_ceiling_breach (MP unit) | {len(mp_fl):,} MPs | {int(mp_fl.sum())} | {_pct(mp_fl.mean())} |")

    # Duplicate: real rows outside (MP, constituency) units that host an injected duplicate
    dup["_unit"] = list(zip(proj.set_index("id").loc[dup.index, "mp_name"].map(rules.normalize_mp_name),
                            proj.set_index("id").loc[dup.index, "constituency"].fillna("").map(rules._norm)))
    dhost = set(dup.loc[dup["anomaly_type"] == "duplicate_work", "_unit"])
    real_du = dup[~dup["is_synthetic_anomaly"].fillna(False) & ~dup["_unit"].isin(dhost)]
    du_units = real_du.groupby("_unit")["flagged"].any()
    w(f"| duplicate_work (row) | {len(real_du):,} projects, {len(dhost)} host units excluded | "
      f"{int(real_du['flagged'].sum()):,} | {_pct(real_du['flagged'].mean())} |")
    w(f"| duplicate_work (MP+constituency unit) | {len(du_units):,} units | {int(du_units.sum())} | "
      f"{_pct(du_units.mean())} |")

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

    for kind in ["cost_inflation", "stalled_project", "duplicate_work", "allocation_ceiling_breach"]:
        n = int(ceiling[ceiling["anomaly_type"] == kind]["flagged"].sum())
        w(f"- allocation_ceiling_breach fired on {n} `{kind}` rows")
    for kind in ["cost_inflation", "stalled_project", "allocation_ceiling_breach", "duplicate_work"]:
        n = int(dup[dup["anomaly_type"] == kind]["flagged"].sum())
        w(f"- duplicate_work fired on {n} `{kind}` rows")
    w("")

    # ---------------- measured weights ----------------
    # log-linear through the two project-grain anchors, capped at 45; duplicate_work then
    # manually overridden to 35 (see the note in risk_scorer.RULE_POINTS)
    fp = {"cost_anomaly": real_cost["flagged"].mean(), "stalled_project": real_stall["flagged"].mean(),
          "allocation_ceiling_breach": appl["flagged"].mean(), "duplicate_work": real_du["flagged"].mean()}
    slope = (40 - 15) / (np.log(fp["cost_anomaly"]) - np.log(fp["stalled_project"]))
    w("## Measured weights (project-grain flag rate on real rows; lower FP -> more points)\n")
    w(f"anchors: cost_anomaly {_pct(fp['cost_anomaly'])} -> 40, stalled_project "
      f"{_pct(fp['stalled_project'])} -> 15; slope {slope:.1f} points per ln-unit; cap 45; "
      f"duplicate_work manually overridden to 35 (precision concern from reviewing flagged samples)\n")
    w("| rule | FP rate | formula | capped | provisional | delta |")
    w("|---|--:|--:|--:|--:|--:|")
    override = {"duplicate_work": 35}
    for code, prov in [("allocation_ceiling_breach", 45), ("duplicate_work", 20)]:
        f = 40 + slope * (np.log(fp[code]) - np.log(fp["cost_anomaly"]))
        final = override.get(code, min(45, round(f)))
        tag = " (manual override)" if code in override else ""
        w(f"| {code} | {fp[code] * 100:.2f}% | {f:.1f} | {final}{tag} | {prov} | {final - prov:+d} |")
    w("")

    # ---------------- sample reasons ----------------
    w("## Sample reasons\n```")
    for frame, col in [(cost, "reason"), (stalled, "reason"), (ceiling, "reason"), (dup, "reason")]:
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
