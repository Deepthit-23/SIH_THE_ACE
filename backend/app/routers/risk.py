from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Project, RiskFlag
from app.schemas import RiskListItem, RiskListPage, severity_band

router = APIRouter(prefix="/risk-scores", tags=["risk"])

_amount = func.coalesce(Project.sanctioned_amount, Project.final_amount)

_SORT = {
    "risk": RiskFlag.combined_risk_score,
    "amount": _amount,
    "id": Project.id,
}


def _top_reasons(explanation, n: int = 2) -> list[str]:
    if not isinstance(explanation, list):
        return []
    return [e.get("message", "") for e in explanation[:n] if e.get("message")]


@router.get("", response_model=RiskListPage)
def list_risk_scores(
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort_by: str = Query("risk", pattern="^(risk|amount|id)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    min_score: float | None = Query(None, ge=0, le=100),
    derived_category: str | None = None,
    state: str | None = None,
    district: str | None = None,
    status: str | None = Query(None, pattern="^(recommended|completed)$"),
) -> RiskListPage:
    """Ranked project risk list. Sorted by combined_risk_score desc by default.

    Only the top 1-2 explanation reasons are returned per row; the full ordered
    list is on GET /projects/{id}.
    """
    filters = []
    if min_score is not None:
        filters.append(RiskFlag.combined_risk_score >= min_score)
    if derived_category:
        filters.append(Project.derived_category == derived_category)
    if state:
        filters.append(func.upper(Project.state) == state.upper())
    if district:
        filters.append(func.upper(Project.district) == district.upper())
    if status:
        filters.append(Project.status == status)

    base = select(Project, RiskFlag).join(RiskFlag, RiskFlag.project_id == Project.id).where(*filters)

    total = db.scalar(
        select(func.count()).select_from(
            select(Project.id).join(RiskFlag, RiskFlag.project_id == Project.id).where(*filters).subquery()
        )
    ) or 0

    col = _SORT[sort_by]
    ordering = col.desc() if order == "desc" else col.asc()
    rows = db.execute(
        base.order_by(ordering, Project.id).limit(limit).offset(offset)
    ).all()

    items = []
    for project, rf in rows:
        amount = project.sanctioned_amount or project.final_amount
        items.append(
            RiskListItem(
                id=project.id,
                external_id=project.external_id,
                work_description=project.work_description,
                mp_name=project.mp_name,
                constituency=project.constituency,
                state=project.state,
                district=project.district,
                derived_category=project.derived_category,
                status=project.status,
                amount=amount,
                combined_risk_score=rf.combined_risk_score,
                severity=severity_band(rf.combined_risk_score),
                top_reasons=_top_reasons(rf.explanation),
            )
        )
    return RiskListPage(total=total, limit=limit, offset=offset, items=items)
