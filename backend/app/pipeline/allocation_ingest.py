"""Ingest official SIH MP-allocation PDFs and write a transparent match report.

The supplied PDFs are authoritative ceilings.  The existing MP summary is an
empoweredindian.in-derived eSAKSHI export and remains a separate provenance.
"""
from __future__ import annotations
import argparse, re
from pathlib import Path
import pandas as pd
import pdfplumber
from sqlalchemy import text
from app.config import settings
from app.database import engine
from app.pipeline.names import match_mps

TERM = re.compile(r"\((20\d{2})\s*-\s*(?:20)?(\d{2,4})\)")
def _money(value: object) -> float | None:
    s = re.sub(r"[^0-9.]", "", str(value or ""))
    if not s or s == ".":
        return None
    try:
        return float(s)
    except ValueError:
        return None
def _term(value: object):
    m = TERM.search(str(value or ""))
    if not m: return None, None
    a, b = int(m.group(1)), m.group(2)
    return a, int(b) if len(b)==4 else (a//100)*100 + int(b)
def parse_pdf(path: Path, house: str) -> pd.DataFrame:
    rows=[]
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            # The visual table grid is segmented into one-row fragments by
            # pdfplumber. Use the verified x-coordinate column boundaries and
            # reconstruct each visual text row instead of dropping fragments.
            visual_rows: dict[int, list[dict]] = {}
            for word in page.extract_words():
                visual_rows.setdefault(round(word["top"]), []).append(word)
            for words in visual_rows.values():
                words.sort(key=lambda w: w["x0"])
                serial = next((w["text"] for w in words if w["x0"] < 90 and w["text"].isdigit()), None)
                if not serial: continue
                if house == "Lok Sabha":
                    # PDF text positions sit just inside the drawn column
                    # boundaries (e.g. CHAVAN at x=279.746), hence the small
                    # tolerances below rather than rounded header positions.
                    state = " ".join(w["text"] for w in words if 90 <= w["x0"] < 275)
                    member = " ".join(w["text"] for w in words if 275 <= w["x0"] < 535)
                    constituency = " ".join(w["text"] for w in words if 535 <= w["x0"] < 735)
                    status = ""
                else:
                    state = " ".join(w["text"] for w in words if 90 <= w["x0"] < 206)
                    member = " ".join(w["text"] for w in words if 206 <= w["x0"] < 492)
                    status = " ".join(w["text"] for w in words if 492 <= w["x0"] < 660)
                    constituency = None
                # Numeric allocation values are rightmost and start beyond x=600;
                # their printed x-position varies with digit width, particularly
                # in the Rajya Sabha PDF, so a fixed amount-column edge loses data.
                amount_candidates = [w for w in words if w["x0"] >= 600 and _money(w["text"]) is not None]
                amount = _money(max(amount_candidates, key=lambda w: w["x0"])["text"]) if amount_candidates else None
                elected=member + " " + status
                start,end=_term(member + " " + elected)
                rows.append({"mp_name": re.sub(r"\s*\(20\d{2}.*", "", member).strip(), "state":state,
                  "house":house, "constituency": constituency, "is_nominated":"nominated" in status.lower(),
                  "term_start":start,"term_end":end,"official_allocated_ceiling":amount})
    # Source serial numbers are unique. Do not deduplicate on name/state/value:
    # that could silently discard two official rows sharing those attributes.
    df=pd.DataFrame(rows)
    expected = {"Lok Sabha": 543, "Rajya Sabha": 232}[house]
    if len(df) != expected:
        raise ValueError(f"Expected {expected} {house} rows from {path}, extracted {len(df)}; refusing partial load")
    return df
NL = chr(10)


def report_and_load(df: pd.DataFrame):
    with engine.begin() as c:
        c.execute(text("DELETE FROM mp_allocation"))
        # Pass SQLAlchemy's Connection, not its raw DBAPI connection.  Pandas
        # otherwise guesses SQLite metadata queries against PostgreSQL.
        df.to_sql("mp_allocation", c, if_exists="append", index=False)
    alloc = pd.read_sql("SELECT * FROM mp_allocation ORDER BY id", engine)

    # Works data (real rows only) -> official rows, through the shared two-pass matcher.
    works = pd.read_sql(
        "SELECT mp_name, state, count(*) AS n_projects FROM projects "
        "WHERE NOT COALESCE(is_synthetic_anomaly, false) GROUP BY mp_name, state", engine)
    m = match_mps(works[["mp_name", "state"]], alloc).merge(works, on=["mp_name", "state"])
    m["matched"] = m.alloc_index.notna()
    have_ceiling = m.alloc_index.map(alloc.official_allocated_ceiling).notna()
    total_p = int(m.n_projects.sum())

    # Discrepancy: official ceiling vs the eSAKSHI-derived mp_summary allocation, per MP.
    summ = pd.read_sql("SELECT mp_name, state, allocated_amount FROM mp_summary", engine)
    sm = match_mps(summ[["mp_name", "state"]], alloc).merge(summ, on=["mp_name", "state"])
    sm = sm[sm.alloc_index.notna()].copy()
    sm["official"] = sm.alloc_index.map(alloc.official_allocated_ceiling)
    sm["summary"] = pd.to_numeric(sm.allocated_amount, errors="coerce")
    sm = sm.dropna(subset=["official", "summary"])
    sm["diff_pct"] = (sm.summary - sm.official) / sm.official * 100
    proc = Path(settings.data_dir) / "processed"; proc.mkdir(parents=True, exist_ok=True)
    sm[["mp_name", "official_name", "state", "official", "summary", "diff_pct", "method"]].sort_values(
        "diff_pct", key=abs, ascending=False).to_csv(proc / "allocation_discrepancies.csv", index=False)

    un = m[~m.matched].sort_values("n_projects", ascending=False)
    missing = alloc[alloc.official_allocated_ceiling.isna()]
    counts = alloc.groupby("house").size().to_dict()
    report = [
        f"official rows: {len(alloc)} ({counts})",
        f"ceilings published: {int(alloc.official_allocated_ceiling.notna().sum())}; unpublished (excluded, never treated as 0): "
        + "; ".join(missing.mp_name + " — " + missing.state),
        f"works-data MPs (real rows): {len(m)}; matched {int(m.matched.sum())} "
        f"({m.matched.mean():.1%}); projects covered {int(m[m.matched].n_projects.sum()):,} of {total_p:,} "
        f"({m[m.matched].n_projects.sum() / total_p:.2%}); with an applicable ceiling "
        f"{int(m[have_ceiling].n_projects.sum()):,} projects",
        "match method (MPs): " + ", ".join(f"{k}={v}" for k, v in m.method.value_counts().items()),
        f"UNMATCHED MPs ({len(un)}), by project count: "
        + "; ".join(f"{r.mp_name} [{r.state}] ({r.n_projects}, {r.method})" for r in un.itertuples()),
        f"mp_summary vs official ceiling (matched, both present): {len(sm)} MPs; "
        f"exact {(sm.diff_pct.abs() < .01).sum()}; within 1% {(sm.diff_pct.abs() <= 1).sum()}; "
        f"over 5% {(sm.diff_pct.abs() > 5).sum()}  (per-MP list: allocation_discrepancies.csv)",
    ]
    (proc / "allocation_reconciliation.md").write_text(NL.join(report) + NL)
    print(NL.join(report))
def main():
    raw=Path(settings.data_dir)/"raw"; report_and_load(pd.concat([parse_pdf(raw/"Allocated_Limit_for_Honble_MPs__1_.pdf","Lok Sabha"),parse_pdf(raw/"Allocated_Limit_for_Honble_MPs__2_.pdf","Rajya Sabha")]))
if __name__ == "__main__": main()
