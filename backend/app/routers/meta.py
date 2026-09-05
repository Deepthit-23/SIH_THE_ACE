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
