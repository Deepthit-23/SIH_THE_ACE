from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/filters")
def filter_options(db: Session = Depends(get_db)) -> dict:
    """Option lists + score-band counts for the dashboard filter controls."""
    states = db.execute(
        text("SELECT DISTINCT state FROM projects WHERE state IS NOT NULL ORDER BY state")
    ).scalars().all()
    categories = db.execute(
        text(
            "SELECT DISTINCT derived_category FROM projects "
            "WHERE derived_category IS NOT NULL ORDER BY derived_category"
        )
    ).scalars().all()
    bands = db.execute(
        text(
            """
            SELECT CASE
                     WHEN combined_risk_score >= 70 THEN 'high'
                     WHEN combined_risk_score >= 50 THEN 'medium'
                     WHEN combined_risk_score > 0 THEN 'low'
                     ELSE 'none'
                   END AS band,
                   count(*) AS n
            FROM risk_flags GROUP BY 1
            """
        )
    ).all()
    return {
        "states": states,
        "derived_categories": categories,
        "statuses": ["recommended", "completed"],
        "score_bands": {b.band: b.n for b in bands},
    }


@router.get("/summary")
def national_summary(db: Session = Depends(get_db)) -> dict:
    """National headline figures for the dashboard landing strip.

    Financials are summed from `mp_summary` (774 MPs); flag counts from
    `risk_flags`.
    """
    fin = db.execute(
        text(
            """
            SELECT COALESCE(sum(allocated_amount), 0)     AS allocated,
                   COALESCE(sum(amount_recommended), 0)    AS recommended,
                   COALESCE(sum(total_expenditure), 0)     AS expenditure,
                   COALESCE(sum(completed_works), 0)       AS completed_works,
                   COALESCE(sum(recommended_works), 0)     AS recommended_works,
                   count(*)                                AS mps
            FROM mp_summary
            """
        )
    ).one()

    proj = db.execute(
        text(
            """
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE rf.combined_risk_score >= 70) AS high,
                   count(*) FILTER (WHERE rf.combined_risk_score >= 50
                                      AND rf.combined_risk_score < 70) AS medium,
                   count(*) FILTER (WHERE rf.combined_risk_score > 0
                                      AND rf.combined_risk_score < 50) AS low
            FROM projects p
            LEFT JOIN risk_flags rf ON rf.project_id = p.id
            """
        )
    ).one()

    allocated = float(fin.allocated) or 0.0
    rec = float(fin.recommended) or 0.0
    rec_works = int(fin.recommended_works) or 0
    return {
        "mps": int(fin.mps),
        "allocated_amount": allocated,
        "recommended_amount": rec,
        "total_expenditure": float(fin.expenditure),
        # unambiguous: expenditure as a share of the allocated fund
        "spend_pct_of_allocation": (
            round(float(fin.expenditure) / allocated * 100, 1) if allocated else None
        ),
        "completion_rate_pct": (
            round(int(fin.completed_works) / rec_works * 100, 1) if rec_works else None
        ),
        "completed_works": int(fin.completed_works),
        "recommended_works": rec_works,
        "projects_scored": int(proj.total),
        "flagged_high": int(proj.high or 0),
        "flagged_medium": int(proj.medium or 0),
        "flagged_low": int(proj.low or 0),
    }
