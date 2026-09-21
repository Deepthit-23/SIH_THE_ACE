from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import SCOPE_COLUMN, current_user, scope_label, scope_sql
from app.database import get_db
from app.models import User
from app.pipeline import SNAPSHOT_DATE

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/public-summary")
def public_summary(db: Session = Depends(get_db)) -> dict:
    """Three national headline figures for the sign-in page, which runs BEFORE authentication.

    UNAUTHENTICATED on purpose, so it is deliberately narrow: national aggregates of the public MPLADS
    exports only (no scope, no project, MP or vendor detail, no risk figures). Works are counted from the
    real records; injected validation rows are not "works tracked" and are excluded here.
    """
    row = db.execute(text(
        "SELECT COALESCE(sum(allocated_amount), 0) AS allocated, count(*) AS mps FROM mp_summary")).one()
    works = db.execute(text("SELECT count(*) FROM projects WHERE NOT is_synthetic_anomaly")).scalar() or 0
    return {
        "allocated_amount": float(row.allocated),
        "works_tracked": int(works),
        "mps_covered": int(row.mps),
        "as_of": SNAPSHOT_DATE.isoformat(),
    }


@router.get("/filters")
def filter_options(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    """Option lists + score-band counts for the dashboard filter controls (scoped)."""
    scope, params = scope_sql(user, "p")
    states = db.execute(
        text(f"SELECT DISTINCT p.work_state AS st FROM projects p "
             f"WHERE p.work_state IS NOT NULL{scope} ORDER BY 1"),
        params,
    ).scalars().all()
    categories = db.execute(
        text(
            f"SELECT DISTINCT p.derived_category FROM projects p "
            f"WHERE p.derived_category IS NOT NULL{scope} ORDER BY 1"
        ),
        params,
    ).scalars().all()
    bands = db.execute(
        text(
            f"""
            SELECT CASE
                     WHEN rf.combined_risk_score >= 70 THEN 'high'
                     WHEN rf.combined_risk_score >= 50 THEN 'medium'
                     WHEN rf.combined_risk_score > 0 THEN 'low'
                     ELSE 'none'
                   END AS band,
                   count(*) AS n
            FROM risk_flags rf JOIN projects p ON p.id = rf.project_id
            WHERE 1=1{scope} GROUP BY 1
            """
        ),
        params,
    ).all()
    return {
        "states": states,
        "derived_categories": categories,
        "statuses": ["recommended", "completed"],
        "score_bands": {b.band: b.n for b in bands},
    }


@router.get("/summary")
def summary(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    """Headline figures for the landing strip, scoped to the caller.

    Financials are summed from `mp_summary` (state / MP grain). It has no district
    column, so district users get flag counts but `null` financials -- we don't
    print a number we can't defend. `spend_pct_of_allocation` is spend / allocation
    (the source's own "utilisation %" uses a definition that doesn't reconcile
    with its raw totals, so it is deliberately not shown).
    """
    financials_available = user.role != "district_authority"
    fin = None
    if financials_available:
        fin_scope, fin_params = "", {}
        if user.role in ("state_nodal", "mp_self"):
            # allocations are per MP, so they stay keyed on the MP's own state / name (mp_summary has no location)
            col = {"state_nodal": "state", "mp_self": "mp_name"}[user.role]
            fin_scope, fin_params = f" WHERE lower({col}) = lower(:s)", {"s": user.scope_value or ""}
        fin = db.execute(
            text(
                f"""
                SELECT COALESCE(sum(allocated_amount), 0) AS allocated,
                       COALESCE(sum(amount_recommended), 0) AS recommended,
                       COALESCE(sum(total_expenditure), 0) AS expenditure,
                       COALESCE(sum(completed_works), 0) AS completed_works,
                       COALESCE(sum(recommended_works), 0) AS recommended_works,
                       count(*) AS mps
                FROM mp_summary{fin_scope}
                """
            ),
            fin_params,
        ).one()

    scope, params = scope_sql(user, "p")
    proj = db.execute(
        text(
            f"""
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE rf.combined_risk_score >= 70) AS high,
                   count(*) FILTER (WHERE rf.combined_risk_score >= 50
                                      AND rf.combined_risk_score < 70) AS medium,
                   count(*) FILTER (WHERE rf.combined_risk_score > 0
                                      AND rf.combined_risk_score < 50) AS low
            FROM projects p LEFT JOIN risk_flags rf ON rf.project_id = p.id
            WHERE 1=1{scope}
            """
        ),
        params,
    ).one()

    out = {
        "scope_label": scope_label(user),
        "role": user.role,
        "financials_available": financials_available,
        "projects_scored": int(proj.total),
        "flagged_high": int(proj.high or 0),
        "flagged_medium": int(proj.medium or 0),
        "flagged_low": int(proj.low or 0),
        "mps": None, "allocated_amount": None, "recommended_amount": None,
        "total_expenditure": None, "spend_pct_of_allocation": None,
        "completion_rate_pct": None, "completed_works": None, "recommended_works": None,
    }
    if fin is not None:
        allocated, rec = float(fin.allocated), float(fin.recommended)
        rec_works = int(fin.recommended_works)
        out.update(
            mps=int(fin.mps), allocated_amount=allocated, recommended_amount=rec,
            total_expenditure=float(fin.expenditure),
            spend_pct_of_allocation=round(float(fin.expenditure) / allocated * 100, 1) if allocated else None,
            completion_rate_pct=round(int(fin.completed_works) / rec_works * 100, 1) if rec_works else None,
            completed_works=int(fin.completed_works), recommended_works=rec_works,
        )
    return out
