"""Pick 3-4 demo anchor projects spanning anomaly types + score bands, and write
them to data/processed/demo_anchors.md so you can navigate straight there live.

    docker compose exec backend python -m app.pipeline.demo_anchors

Run after score_projects. Uses the internal `is_synthetic_anomaly` label -- this
is a dev tool, not served anywhere.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from app.config import settings
from app.database import engine


def _load() -> pd.DataFrame:
    return pd.read_sql(
        """
        SELECT p.id, p.mp_name, p.state, p.district, p.derived_category, p.status,
               p.is_synthetic_anomaly, p.anomaly_type,
               COALESCE(p.sanctioned_amount, p.final_amount) AS amount,
               rf.combined_risk_score AS score, rf.rule_flags, rf.explanation
        FROM projects p JOIN risk_flags rf ON rf.project_id = p.id
        """,
        engine,
    )


def _fired(rf: dict, code: str) -> bool:
    return bool(rf.get(code))


def _summary(row: pd.Series) -> str:
    fired = [k for k, v in row["rule_flags"].items() if v]
    ml = [e for e in row["explanation"] if e["source"] == "ml"]
    return (
        f"score {row['score']:.0f} | {row['derived_category']} | {row['state']}/"
        f"{row['district']} | rules: {', '.join(fired) or 'none'}"
        f"{' | +ML' if ml else ''}"
    )


def pick(df: pd.DataFrame) -> list[dict]:
    anchors: list[dict] = []
    used: set[int] = set()

    def take(candidates: pd.DataFrame, label: str, why: str) -> None:
        for _, r in candidates.iterrows():
            if r["id"] in used:
                continue
            used.add(r["id"])
            anchors.append({"label": label, "why": why, "id": int(r["id"]),
                            "summary": _summary(r), "row": r})
            return

    # 1. clean cost_inflation catch: cost rule the dominant signal, high score
    cost = df[
        (df["anomaly_type"] == "cost_inflation")
        & df["rule_flags"].map(lambda rf: _fired(rf, "cost_anomaly"))
    ].copy()
    cost["n_rules"] = cost["rule_flags"].map(lambda rf: sum(rf.values()))
    take(
        cost.sort_values(["n_rules", "score"], ascending=[True, False]),
        "Cost inflation — clean catch",
        "synthetic cost_inflation; cost rule is the driving signal",
    )

    # 2. contractor concentration: project in a synthetic ring MP, contractor rule fired
    con_mps = set(
        pd.read_sql(
            "SELECT DISTINCT mp_name FROM vendor_transactions "
            "WHERE anomaly_type = 'contractor_concentration'",
            engine,
        )["mp_name"]
    )
    con = df[
        df["mp_name"].isin(con_mps)
        & df["rule_flags"].map(lambda rf: _fired(rf, "contractor_concentration"))
    ].sort_values("score", ascending=False)
    take(con, "Contractor concentration", "MP with a synthetic vendor cartel; contractor rule fired")

    # 3. stalled / ghost project
    stalled = df[
        (df["anomaly_type"] == "stalled_project")
        & df["rule_flags"].map(lambda rf: _fired(rf, "stalled_project"))
    ].sort_values("score")
    take(stalled, "Stalled / ghost project", "synthetic stalled_project; the weak-signal rule")

    # 4. mid-tier combined signals: score 50-70, >= 2 rules or rule + ML
    mid = df[(df["score"] >= 50) & (df["score"] < 70)].copy()
    mid["n_rules"] = mid["rule_flags"].map(lambda rf: sum(rf.values()))
    mid["has_ml"] = mid["explanation"].map(lambda e: any(x["source"] == "ml" for x in e))
    mid = mid[(mid["n_rules"] >= 2) | ((mid["n_rules"] >= 1) & mid["has_ml"])]
    take(
        mid.sort_values("score", ascending=False),
        "Mid-tier — combined signals",
        "medium band; rule + ML together, neither alone conclusive",
    )
    return anchors


def render(anchors: list[dict]) -> str:
    lines = ["# Demo anchor projects", ""]
    lines.append("Navigate to `/projects/<id>`. Regenerate after any pipeline re-run.\n")
    for a in anchors:
        lines.append(f"## {a['label']} — **project {a['id']}**")
        lines.append(f"- {a['why']}")
        lines.append(f"- {a['summary']}")
        r = a["row"]
        for e in r["explanation"]:
            lines.append(f"  - [{e['source']}] {e['message']}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    df = _load()
    if df.empty:
        print("no risk_flags -- run score_projects first")
        return 1
    anchors = pick(df)
    report = render(anchors)
    print(report)
    dest = Path(settings.data_dir).resolve() / "processed" / "demo_anchors.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(report, encoding="utf-8")
    print(f"written -> {dest}")
    print("\nIDs:", json.dumps([a["id"] for a in anchors]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
