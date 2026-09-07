import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import CaseReview, Project, RiskFlag
from app.schemas import RiskListItem, RiskListPage, severity_band

router = APIRouter(prefix="/risk-scores", tags=["risk"])

_amount = func.coalesce(Project.sanctioned_amount, Project.final_amount)

_SORT = {
    "risk": RiskFlag.combined_risk_score,
    "amount": _amount,
    "id": Project.id,
}
_CASE_STATUSES = ("pending", "under_review", "confirmed", "dismissed")


def _top_reasons(explanation, n: int = 2) -> list[str]:
    if not isinstance(explanation, list):
        return []
    return [e.get("message", "") for e in explanation[:n] if e.get("message")]


def _risk_filters(min_score, derived_category, state, district, status, case_status, q):
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
    if case_status in _CASE_STATUSES:
        if case_status == "pending":
            filters.append(or_(CaseReview.id.is_(None), CaseReview.status == "pending"))
        else:
            filters.append(CaseReview.status == case_status)
    if q and q.strip():
        like = f"%{q.strip()}%"
        filters.append(
            or_(
                Project.mp_name.ilike(like),
                Project.work_description.ilike(like),
                Project.external_id.ilike(like),
            )
        )
    return filters


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
    case_status: str | None = Query(None),
    q: str | None = Query(None, description="search MP name / work description / Work ID"),
) -> RiskListPage:
    """Ranked project risk list. Sorted by combined_risk_score desc by default.

    Only the top 1-2 explanation reasons are returned per row; the full ordered
    list is on GET /projects/{id}.
    """
    filters = _risk_filters(
        min_score, derived_category, state, district, status, case_status, q
    )

    base = (
        select(Project, RiskFlag, CaseReview)
        .join(RiskFlag, RiskFlag.project_id == Project.id)
        .outerjoin(CaseReview, CaseReview.project_id == Project.id)
        .where(*filters)
    )
    count_stmt = (
        select(func.count())
        .select_from(Project)
        .join(RiskFlag, RiskFlag.project_id == Project.id)
        .outerjoin(CaseReview, CaseReview.project_id == Project.id)
        .where(*filters)
    )
    total = db.scalar(count_stmt) or 0

    col = _SORT[sort_by]
    ordering = col.desc() if order == "desc" else col.asc()
    rows = db.execute(
        base.order_by(ordering, Project.id).limit(limit).offset(offset)
    ).all()

    items = [
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
            amount=project.sanctioned_amount or project.final_amount,
            combined_risk_score=rf.combined_risk_score,
            severity=severity_band(rf.combined_risk_score),
            case_status=cr.status if cr is not None else "pending",
            top_reasons=_top_reasons(rf.explanation),
        )
        for project, rf, cr in rows
    ]
    return RiskListPage(total=total, limit=limit, offset=offset, items=items)


_CSV_COLUMNS = [
    "project_id", "work_id", "work_description", "mp_name", "constituency", "state",
    "district", "category", "work_status", "amount_inr", "risk_score", "severity",
    "case_status", "top_reason_1", "top_reason_2",
]


@router.get("/export.csv")
def export_csv(
    db: Session = Depends(get_db),
    min_score: float | None = Query(None, ge=0, le=100),
    derived_category: str | None = None,
    state: str | None = None,
    district: str | None = None,
    status: str | None = Query(None, pattern="^(recommended|completed)$"),
    case_status: str | None = Query(None),
    q: str | None = Query(None),
) -> StreamingResponse:
    """Flagged list as CSV for an audit team to work offline. Honours the same
    filters as GET /risk-scores (no pagination -- streams every match)."""
    filters = _risk_filters(
        min_score, derived_category, state, district, status, case_status, q
    )
    stmt = (
        select(Project, RiskFlag, CaseReview)
        .join(RiskFlag, RiskFlag.project_id == Project.id)
        .outerjoin(CaseReview, CaseReview.project_id == Project.id)
        .where(*filters)
        .order_by(RiskFlag.combined_risk_score.desc(), Project.id)
    )

    def rows():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(_CSV_COLUMNS)
        yield buf.getvalue()
        buf.seek(0), buf.truncate(0)
        for project, rf, cr in db.execute(stmt).yield_per(2000):
            reasons = _top_reasons(rf.explanation, 2) + ["", ""]
            w.writerow([
                project.id, project.external_id or "", project.work_description or "",
                project.mp_name or "", project.constituency or "", project.state or "",
                project.district or "", project.derived_category or "", project.status or "",
                project.sanctioned_amount or project.final_amount or "",
                rf.combined_risk_score, severity_band(rf.combined_risk_score),
                cr.status if cr is not None else "pending", reasons[0], reasons[1],
            ])
            yield buf.getvalue()
            buf.seek(0), buf.truncate(0)

    fname = f"mplad_flagged_{date.today().isoformat()}.csv"
    return StreamingResponse(
        rows(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
