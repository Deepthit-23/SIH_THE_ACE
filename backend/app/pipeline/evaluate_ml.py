"""Evaluate the ML detector and the rules+ML combination against the synthetic
anomalies -- directly comparable to `evaluate_rules.py`.

    docker compose exec backend python -m app.pipeline.evaluate_ml

Reports:
  1. contamination sweep (recall vs. project-grain synthetics, FP on real projects)
  2. recall by anomaly_type: rules only | ML only | combined
  3. project-level false-positive rate: rules | ML | combined
  4. the headline delta -- synthetic anomalies ML caught that the rules missed
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pandas as pd

from app.config import settings
from app.database import engine
from app.pipeline import ml_model, risk_scorer, rules

CONTAMINATION = 0.04
SWEEP = [0.01, 0.02, 0.03, 0.04, 0.05, 0.08]


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%" if x == x else "n/a"


def build_report() -> str:
    proj = pd.read_sql("SELECT * FROM projects ORDER BY id", engine)
    vtx = pd.read_sql("SELECT * FROM vendor_transactions ORDER BY id", engine)
    mps = pd.read_sql("SELECT * FROM mp_summary ORDER BY id", engine)
    out = io.StringIO()

    def w(s: str = "") -> None:
        out.write(s + "\n")

    truth = proj.set_index("id")[["is_synthetic_anomaly", "anomaly_type"]]
    truth["is_synthetic_anomaly"] = truth["is_synthetic_anomaly"].astype(bool)
    syn_ids = {
        k: set(truth.index[truth["anomaly_type"] == k])
        for k in ["cost_inflation", "stalled_project"]
    }

    # rule outputs (once)
    cost = rules.cost_anomaly(proj)
    stalled = rules.stalled_project(proj, vtx, mps)
    contractor = rules.contractor_concentration(vtx)
    payment = rules.payment_gap(vtx, mps)

    # feature matrix (once); models per contamination
    X = ml_model.build_feature_matrix(proj, vtx, mps)
    real_proj_mask = ~truth["is_synthetic_anomaly"].reindex(X.index).fillna(False).to_numpy()

    w("# ML + combined evaluation\n")
    w(f"_db: {settings.database_url.split('@')[-1]}_\n")
    w(f"feature matrix: {X.shape[0]:,} projects x {X.shape[1]} features "
      f"(labels NOT used as input)\n")

    # ---------------- 1. contamination sweep ----------------
    w("## 1. Contamination sweep\n")
    w("| contamination | ML flagged | cost_inflation recall | stalled recall | FP (real projects) |")
    w("|--:|--:|--:|--:|--:|")
    for c in SWEEP:
        m = ml_model.train_isolation_forest(X, contamination=c)
        s = ml_model.score(m, X)
        fl = s["ml_flag"]
        r_cost = fl.reindex(list(syn_ids["cost_inflation"])).mean()
        r_stall = fl.reindex(list(syn_ids["stalled_project"])).mean()
        fp = fl[real_proj_mask].mean()
        w(f"| {c} | {int(fl.sum()):,} | {_pct(r_cost)} | {_pct(r_stall)} | {_pct(fp)} |")
    w(f"\n_using contamination = {CONTAMINATION} for the tables below_\n")

    # ---------------- main model ----------------
    model = ml_model.train_isolation_forest(X, contamination=CONTAMINATION)
    ml = ml_model.score(model, X)
    stats = ml_model.population_stats(X)
    explain_idx = ml.index[ml["ml_flag"] | (ml["ml_percentile"] >= 92.0)]
    fragments = ml_model.explain_fragments(X, explain_idx, stats)
    ml["ml_reason"] = pd.Series(
        ml_model.explain_projects(X, explain_idx, stats)
    ).reindex(ml.index)

    combined = risk_scorer.combine(
        proj, cost, stalled, contractor, payment, ml, ml_fragments=fragments
    )
    pid = proj["id"]
    cost_flag = cost["flagged"].astype(bool).reindex(pid, fill_value=False)
    stalled_flag = stalled["flagged"].astype(bool).reindex(pid, fill_value=False)
    ml_flag = (ml["ml_flag"] == True).reindex(pid, fill_value=False)  # noqa: E712
    any_rule = (combined["rule_score"] > 0).reindex(pid).fillna(False)
    combo_score = combined["combined_risk_score"].reindex(pid)

    t = truth.reindex(pid)
    t["status"] = proj.set_index("id")["status"].reindex(pid).to_numpy()
    t["cost_flag"] = cost_flag.to_numpy()
    t["stalled_flag"] = stalled_flag.to_numpy()
    t["ml_flag"] = ml_flag.to_numpy()
    t["any_rule"] = any_rule.to_numpy()
    t["combo_score"] = combo_score.to_numpy()
    # the rule that is actually responsible for this anomaly_type
    t["own_rule"] = np.where(
        t["anomaly_type"] == "cost_inflation", t["cost_flag"],
        np.where(t["anomaly_type"] == "stalled_project", t["stalled_flag"], False),
    )
    t["union"] = t["own_rule"].astype(bool) | t["ml_flag"]

    # synthetic vendor-grain units
    vlabel, _ = rules._geo_unit(vtx)
    vtx2 = vtx.assign(_unit=vlabel)
    con_units = set(vtx2.loc[vtx2["anomaly_type"] == "contractor_concentration", "mp_name"])
    pay_units = set(
        map(tuple, vtx2.loc[vtx2["anomaly_type"] == "payment_gap", ["mp_name", "constituency"]].values)
    )
    proj_key_mp = proj.set_index("id")["mp_name"]
    proj_key_mpc = proj.set_index("id").apply(lambda r: (r["mp_name"], r["constituency"]), axis=1)

    def unit_recall(units, project_key: pd.Series, flag: pd.Series) -> tuple[int, int]:
        hit = 0
        for u in units:
            pids = project_key.index[project_key.map(lambda x: x == u)]
            if len(pids) and bool(flag.reindex(pids).fillna(False).any()):
                hit += 1
        return hit, len(units)

    flagged_con_mps = set(contractor.loc[contractor["flagged"], "mp_name"])
    flagged_pay_keys = set(
        map(tuple, payment.loc[payment["flagged"], ["mp_name", "constituency"]].values)
    )
    def unit_combined(units, key: pd.Series, rule_hit_set) -> int:
        hit = 0
        for u in units:
            if u in rule_hit_set:
                hit += 1
                continue
            pids = key.index[key.map(lambda x: x == u)]
            if len(pids) and bool(ml_flag.reindex(pids).fillna(False).any()):
                hit += 1
        return hit

    con_rule_hit = len(con_units & flagged_con_mps)
    pay_rule_hit = len(pay_units & flagged_pay_keys)
    con_ml_hit, con_tot = unit_recall(con_units, proj_key_mp, ml_flag)
    pay_ml_hit, pay_tot = unit_recall(pay_units, proj_key_mpc, ml_flag)
    con_union_hit = unit_combined(con_units, proj_key_mp, flagged_con_mps)
    pay_union_hit = unit_combined(pay_units, proj_key_mpc, flagged_pay_keys)

    # ---------------- 2. recall by anomaly_type ----------------
    w("## 2. Recall by anomaly_type: responsible rule | ML | combined\n")
    w("_'rule' = the rule targeting that anomaly type (cost rule for cost_inflation, "
      "stalled rule for stalled_project); matches the Phase 3 numbers._\n")
    w("| anomaly_type | grain | population | rule | ML | combined |")
    w("|---|---|--:|--:|--:|--:|")
    for kind, flagcol in [("cost_inflation", "cost_flag"), ("stalled_project", "stalled_flag")]:
        sub = t[t["anomaly_type"] == kind]
        n = len(sub)
        w(f"| {kind} | project | {n} | {_pct(sub[flagcol].mean())} | "
          f"{_pct(sub['ml_flag'].mean())} | {_pct(sub['union'].mean())} |")
    w(f"| contractor_concentration | MP unit | {con_tot} | "
      f"{_pct(con_rule_hit / con_tot)} | {_pct(con_ml_hit / con_tot)} | {_pct(con_union_hit / con_tot)} |")
    w(f"| payment_gap | MP-const unit | {pay_tot} | "
      f"{_pct(pay_rule_hit / pay_tot)} | {_pct(pay_ml_hit / pay_tot)} | {_pct(pay_union_hit / pay_tot)} |")

    proj_syn = t[t["anomaly_type"].isin(["cost_inflation", "stalled_project"])]
    w(f"\n**Project-grain synthetic recall: rules {_pct(proj_syn['own_rule'].astype(bool).mean())} | "
      f"ML {_pct(proj_syn['ml_flag'].mean())} | combined {_pct(proj_syn['union'].mean())}**\n")

    # ---------------- 3. false positives ----------------
    real = t[~t["is_synthetic_anomaly"].fillna(False)]
    real_rec = real[real["status"] == "recommended"]
    w("## 3. False-positive rate (real rows)\n")
    w("| detector | denominator | flagged | FP rate |")
    w("|---|--:|--:|--:|")
    w(f"| cost rule | {len(real):,} projects | {int(real['cost_flag'].sum()):,} | {_pct(real['cost_flag'].mean())} |")
    w(f"| stalled rule | {len(real_rec):,} recommended | {int(real_rec['stalled_flag'].sum()):,} | {_pct(real_rec['stalled_flag'].mean())} |")
    w(f"| ML (isolation forest) | {len(real):,} projects | {int(real['ml_flag'].sum()):,} | {_pct(real['ml_flag'].mean())} |")
    for thr in (50, 60, 70):
        w(f"| combined score >= {thr} | {len(real):,} projects | "
          f"{int((real['combo_score'] >= thr).sum()):,} | {_pct((real['combo_score'] >= thr).mean())} |")
    w("")

    # ---------------- 4. the delta ----------------
    w("## 4. ML value-add: synthetic anomalies ML caught that the rules MISSED\n")
    w("| anomaly_type | rules missed | of those, ML caught | net new from ML |")
    w("|---|--:|--:|--:|")
    total_new = 0
    for kind in ["cost_inflation", "stalled_project"]:
        sub = t[t["anomaly_type"] == kind]
        missed = ~sub["own_rule"].astype(bool)
        ml_saved = missed & sub["ml_flag"]
        total_new += int(ml_saved.sum())
        w(f"| {kind} | {int(missed.sum())} | {int(ml_saved.sum())} | "
          f"{_pct(ml_saved.sum() / len(sub))} of population |")
    con_new = con_union_hit - con_rule_hit
    pay_new = pay_union_hit - pay_rule_hit
    w(f"| contractor_concentration | {con_tot - con_rule_hit} | {max(0, con_new)} | {max(0, con_new)} units |")
    w(f"| payment_gap | {pay_tot - pay_rule_hit} | {max(0, pay_new)} | {max(0, pay_new)} units |")
    w(f"\n**Net new project-grain synthetic anomalies from the ML layer: {total_new}** "
      f"(out of {len(proj_syn)} synthetic project rows)\n")

    # also: rules-caught that ML missed (context)
    rc_ml_missed = int((proj_syn["own_rule"].astype(bool) & ~proj_syn["ml_flag"]).sum())
    w(f"_For context: rules caught {rc_ml_missed} project-grain synthetics that ML missed._\n")

    # ---------------- sample ML reasons (as shown in the final explanation) ----------------
    w("## Sample ML reasons (post rule-coverage suppression)\n```")
    seen = set()
    for expl in combined["explanation"]:
        for e in expl:
            if e["source"] == "ml" and e["message"] not in seen:
                seen.add(e["message"])
                w(f"- {e['message']}")
        if len(seen) >= 12:
            break
    w("```")

    return out.getvalue()


def main() -> int:
    report = build_report()
    print(report)
    dest = Path(settings.data_dir).resolve() / "processed" / "ml_eval.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(report, encoding="utf-8")
    print(f"\nwritten -> {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
