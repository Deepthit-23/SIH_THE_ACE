"""Pick demo anchors and write data/processed/demo_anchors.md.

Two parts:
  A. one anchor per anomaly type (all six rules) + an ML-feature example;
  B. a role walkthrough: at least one in-scope, meaningful project for each of the four demo
     roles (ministry / state / district / MP), with case-review guidance.

Every anchor is checked against the REAL API: the four demo accounts log in through /auth/login
and request /projects/{id} and /projects/{id}/case, so the access matrix in the output is what
each role will actually see (200 vs 403), not an assumption. Nothing is written to the database.

    docker compose exec backend python -m app.pipeline.demo_anchors

Run after score_projects. Uses the internal `is_synthetic_anomaly` / `anomaly_type` labels to
choose part-A anchors -- a dev tool; the labels are never served by the API.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient
from rapidfuzz import fuzz, utils

from app.auth import DEMO_USERS, seed_demo_users
from app.config import settings
from app.database import SessionLocal, engine

ROLE_ORDER = ["ministry", "state_nodal", "district_authority", "mp_self"]
ROLE_NAME = {"ministry": "Ministry", "state_nodal": "State", "district_authority": "District", "mp_self": "MP"}


def _load() -> pd.DataFrame:
    df = pd.read_sql(
        """
        SELECT p.id, p.external_id, p.work_description, p.mp_name, p.constituency, p.state,
               p.district, p.derived_category, p.status, p.recommendation_date,
               p.completion_date, p.is_synthetic_anomaly AS syn, p.anomaly_type,
               COALESCE(p.sanctioned_amount, p.final_amount) AS amount,
               rf.combined_risk_score AS score, rf.rule_flags, rf.explanation,
               cr.status AS case_status
        FROM projects p
        JOIN risk_flags rf ON rf.project_id = p.id
        LEFT JOIN case_reviews cr ON cr.project_id = p.id
        """,
        engine,
    )
    df["fired"] = df["rule_flags"].map(lambda r: [k for k, v in r.items() if v])
    df["n_rules"] = df["fired"].map(len)
    df["has_ml"] = df["explanation"].map(lambda e: any(x["source"] == "ml" for x in e))
    df["case_status"] = df["case_status"].fillna("pending")
    return df


def _band(score: float) -> str:
    return "high" if score >= 70 else "medium" if score >= 50 else "low"


def _first(df: pd.DataFrame, used: set[int]):
    for _, r in df.iterrows():
        if int(r["id"]) not in used:
            return r
    return None


# --------------------------------------------------------------------------- #
# Part A: one anchor per anomaly type
# --------------------------------------------------------------------------- #
def pick_types(df: pd.DataFrame) -> list[dict]:
    out: list[dict] = []
    used: set[int] = set()

    def take(label: str, why: str, cand: pd.DataFrame, extra: str = "") -> None:
        r = _first(cand, used)
        if r is None:
            out.append({"label": label, "why": why + "  **(no candidate found)**", "row": None, "extra": ""})
            return
        used.add(int(r["id"]))
        out.append({"label": label, "why": why, "row": r, "extra": extra})

    def fired(code):
        return df["fired"].map(lambda f: code in f)

    # 1 cost anomaly: cleanest catch -- cost rule fires, fewest other signals, highest score
    take("Cost anomaly", "injected cost inflation; the cost rule is the driving signal",
         df[(df.anomaly_type == "cost_inflation") & fired("cost_anomaly")]
         .sort_values(["n_rules", "score"], ascending=[True, False]))

    # 2 contractor concentration: project of an MP with an injected vendor ring, rule fired
    ring = set(pd.read_sql("SELECT DISTINCT mp_name FROM vendor_transactions "
                           "WHERE anomaly_type = 'contractor_concentration'", engine)["mp_name"])
    take("Contractor concentration", "MP with an injected vendor ring; the contractor rule fired",
         df[df.mp_name.isin(ring) & fired("contractor_concentration")].sort_values("score", ascending=False))

    # 3 stalled / ghost project
    take("Stalled / ghost project", "injected stalled project; the weakest rule (15 points) on its own",
         df[(df.anomaly_type == "stalled_project") & fired("stalled_project")].sort_values("score"))

    # 4 payment gap
    pg = set(pd.read_sql("SELECT DISTINCT mp_name FROM vendor_transactions "
                         "WHERE anomaly_type = 'payment_gap'", engine)["mp_name"])
    take("Payment gap", "MP with an injected burst of in-progress payments; the payment rule fired",
         df[df.mp_name.isin(pg) & fired("payment_gap")].sort_values("score", ascending=False))

    # 5 allocation ceiling breach: prefer an injected breach project that the rule itself flagged
    take("Allocation ceiling breach",
         "project that pushed the MP's running total past their official ceiling (rule weight 45)",
         df[fired("allocation_ceiling_breach")]
         .assign(_fx=lambda d: (d.anomaly_type == "allocation_ceiling_breach").astype(int))
         .sort_values(["_fx", "n_rules", "score"], ascending=[False, True, False]))

    # 6 duplicate work: an injected re-claim flagged by the duplicate rule alone (weight 35, manual override)
    dup = df[(df.anomaly_type == "duplicate_work") & fired("duplicate_work")]
    take("Duplicate work",
         "re-claim of an earlier work: same MP + constituency, near-identical text, amount within 15%, "
         "dates >= 30 days apart (rule weight 35, a manual override)",
         dup.assign(_solo=lambda d: (d.n_rules == 1).astype(int)).sort_values(["_solo", "score"], ascending=[False, False]),
         extra="dup_pair")

    # 7 ML feature example: the model cites one of the two new features with no rule covering it
    def ml_new_feature(e):
        return any(x["source"] == "ml" and ("allocation ceiling" in x["message"] or "closely resembles" in x["message"])
                   for x in e)
    take("ML-only signal (new features)",
         "the anomaly model cites ceiling utilisation or duplicate similarity where no rule fired for it",
         df[df.explanation.map(ml_new_feature) & (df.n_rules == 0)].sort_values("score", ascending=False))
    return out


def dup_partner(df: pd.DataFrame, row: pd.Series):
    """Best same-MP, same-constituency counterpart of a duplicate-flagged project."""
    peers = df[(df.mp_name == row.mp_name) & (df.constituency == row.constituency) & (df.id != row.id)]
    if peers.empty:
        return None
    sc = peers.work_description.map(
        lambda d: fuzz.token_sort_ratio(str(d), str(row.work_description), processor=utils.default_process)
    )
    best = peers.assign(_s=sc).sort_values("_s", ascending=False).iloc[0]
    return best if best["_s"] >= 80 else None


# --------------------------------------------------------------------------- #
# Part B: role walkthrough
# --------------------------------------------------------------------------- #
def scope_of(role: str) -> dict:
    for u, _, r, scope in DEMO_USERS:
        if r == role:
            return {"user": u, "scope": scope}
    raise KeyError(role)


def pick_roles(df: pd.DataFrame) -> list[dict]:
    real = df[~df.syn.astype(bool)]
    picks: list[dict] = []
    st = scope_of("state_nodal")["scope"]
    di = scope_of("district_authority")["scope"]
    mp = scope_of("mp_self")["scope"]

    def best(d: pd.DataFrame):
        return d.sort_values(["n_rules", "score"], ascending=[False, False]).head(1)

    inside_any = (real.state.str.lower() == st.lower()) | (real.district.str.lower() == di.lower()) \
        | (real.mp_name.str.lower() == mp.lower())
    m = best(real[~inside_any & (real.score >= 70) & (real.n_rules >= 2) & (real.case_status == "pending")])
    picks.append({"role": "ministry", "row": m.iloc[0], "line":
                  "National view. This project sits OUTSIDE the state, district and MP demo scopes, so it is "
                  "the one to show the ministry seeing something the other three roles get a 403 for."})
    s = best(real[(real.state.str.lower() == st.lower()) & (real.score >= 70) & (real.n_rules >= 2)])
    picks.append({"role": "state_nodal", "row": s.iloc[0], "line":
                  f"State nodal officer for {st}: a multi-signal flag inside their state, ready to confirm or dismiss."})
    d = best(real[(real.district.str.lower() == di.lower()) & (real.score >= 70) & (~real.id.isin([s.iloc[0]["id"]]))])
    picks.append({"role": "district_authority", "row": d.iloc[0], "line":
                  f"District authority for {di}: a high-score flag in their district (a different project from "
                  "the state one, so the two logins tell different stories). District users see no MP-level "
                  "allocation totals, only project flags."})
    p = best(real[(real.mp_name.str.lower() == mp.lower()) & (real.score >= 70)])
    picks.append({"role": "mp_self", "row": p.iloc[0], "line":
                  "MP self-view: the MP sees only their own portfolio, read-only. Frame it as 'here is what has "
                  "been flagged in your portfolio', a prompt to review, not a finding."})
    return picks


# --------------------------------------------------------------------------- #
# access matrix via the real API
# --------------------------------------------------------------------------- #
def access_matrix(ids: list[int]) -> dict[int, dict[str, str]]:
    from app.main import app  # imported late: needs DB + settings

    with SessionLocal() as db:
        seed_demo_users(db)
    client = TestClient(app)
    tokens = {}
    for username, password, role, _ in DEMO_USERS:
        r = client.post("/auth/login", json={"username": username, "password": password})
        r.raise_for_status()
        tokens[role] = {"Authorization": f"Bearer {r.json()['access_token']}"}
    out: dict[int, dict[str, str]] = {}
    for pid in ids:
        out[pid] = {}
        for role in ROLE_ORDER:
            r = client.get(f"/projects/{pid}", headers=tokens[role])
            c = client.get(f"/projects/{pid}/case", headers=tokens[role])
            out[pid][role] = f"{r.status_code}/{c.status_code}"
    return out


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
def _fmt_amount(v) -> str:
    return "n/a" if v is None or pd.isna(v) else f"Rs {float(v) / 1e5:,.2f} L"


def _block(lines: list[str], title: str, r: pd.Series, matrix: dict, why: str) -> None:
    pid = int(r["id"])
    lines.append(f"### {title} — project **{pid}**")
    lines.append(f"- {why}")
    lines.append(f"- open: `/projects/{pid}`  ·  work id {r['external_id']}  ·  {_band(r['score'])} band, "
                 f"**score {r['score']:.1f}**")
    lines.append(f"- {r['mp_name']} · {r['constituency']} · {r['district']}, {r['state']} · "
                 f"{r['status']} · {_fmt_amount(r['amount'])} · case: {r['case_status']}")
    lines.append(f"- rules fired: {', '.join(r['fired']) or 'none'}{'  ·  +ML' if r['has_ml'] else ''}")
    for e in r["explanation"]:
        lines.append(f"  - [{e['source']}] {e['message']}")
    m = matrix.get(pid, {})
    cells = "  ".join(f"{ROLE_NAME[k]} {m.get(k, '?')}" for k in ROLE_ORDER)
    lines.append(f"- access (project/case HTTP status): {cells}")
    lines.append("")


def render(types: list[dict], roles: list[dict], df: pd.DataFrame, matrix: dict) -> str:
    L = ["# Demo anchor projects", ""]
    L.append("Generated by `python -m app.pipeline.demo_anchors` after the latest scoring run "
             "(ceiling = running-total crossing rule, duplicate weight 35, 30-feature model). "
             "Regenerate after any `inject_anomalies` / `score_projects` run — synthetic IDs change.")
    L.append("")
    L.append("Sign in with the demo accounts: `ministry_demo`, `state_demo`, `district_demo`, `mp_demo` "
             "(passwords in the README). The access lines below come from real API calls made with those "
             "accounts (`200` = visible, `403` = outside the account's scope).")
    L.append("")
    L.append("## Part A — one anchor per anomaly type\n")
    L.append("_Types are chosen with the internal synthetic labels; the UI never shows them._\n")
    for a in types:
        if a["row"] is None:
            L.append(f"### {a['label']}\n- {a['why']}\n")
            continue
        _block(L, a["label"], a["row"], matrix, a["why"])
        if a["extra"] == "dup_pair":
            partner = dup_partner(df, a["row"])
            if partner is not None:
                L.append(f"  - counterpart to open alongside: project **{int(partner['id'])}** "
                         f"(work id {partner['external_id']}, {_fmt_amount(partner['amount'])}) — "
                         f"\"{str(partner['work_description'])[:90]}\"")
                L.append("")
    L.append("## Part B — role walkthrough\n")
    L.append("Suggested order: Ministry -> State -> District -> MP, then try each project while signed in as a "
             "different role to show the scope wall.\n")
    for a in roles:
        info = scope_of(a["role"])
        _block(L, f"{ROLE_NAME[a['role']]} (`{info['user']}`, scope: {info['scope'] or 'all India'})",
               a["row"], matrix, a["line"])
    L.append("### Case-review walkthrough\n")
    L.append("- **State / district:** open their project above, set *Under review*, then *Confirmed* or "
             "*Dismissed* (a dismissal needs a reason). Both are allowed inside their own scope.\n"
             "- **Ministry:** open the same case afterwards and override it. Once the ministry decides, "
             "non-ministry accounts are locked out of changing it.\n"
             "- **MP:** case history is visible on their own projects only; the MP account cannot change a case.\n"
             "- Every change is appended to the audit hash-chain; the header chip stays green.\n"
             "- This tool does not create cases (it never writes to the database), so the clicks are done "
             "live. Cases persist across re-scoring, so a case set in a rehearsal stays set: pick a fresh "
             "pending project for the real run.")
    cases = pd.read_sql(
        "SELECT project_id, status, note, reviewer FROM case_reviews ORDER BY updated_at", engine)
    if len(cases):
        L.append("")
        L.append("**Existing cases in the log** (an example of a finished case; the reviewer is blank when it "
                 "was recorded before role-based accounts existed):")
        for c in cases.itertuples():
            by = f" by {c.reviewer}" if c.reviewer else ""
            note = f" — “{str(c.note)[:110]}”" if c.note else ""
            L.append(f"- project {c.project_id}: {c.status}{by}{note}")
    L.append("")
    return "\n".join(L)


def main() -> int:
    df = _load()
    if df.empty:
        print("no risk_flags -- run score_projects first")
        return 1
    types = pick_types(df)
    roles = pick_roles(df)
    ids = [int(a["row"]["id"]) for a in types if a["row"] is not None] + [int(a["row"]["id"]) for a in roles]
    for a in types:
        if a["extra"] == "dup_pair" and a["row"] is not None:
            p = dup_partner(df, a["row"])
            if p is not None:
                ids.append(int(p["id"]))
    matrix = access_matrix(sorted(set(ids)))
    report = render(types, roles, df, matrix)
    print(report)
    dest = Path(settings.data_dir).resolve() / "processed" / "demo_anchors.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(report, encoding="utf-8")
    print(f"written -> {dest}")
    print("\nIDs:", json.dumps(sorted(set(ids))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
