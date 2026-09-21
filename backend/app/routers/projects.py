from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import assert_project_scope, current_user, scope_project_query
from app.models import User
from app.models import CaseReview, Project, RiskFlag
from app.schemas import (
    ExplanationItem,
    ProjectDetail,
    ProjectList,
    ProjectOut,
    severity_band,
)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=ProjectList)
def list_projects(
    db: Session = Depends(get_db), user: User = Depends(current_user),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    state: str | None = None,
    district: str | None = None,
) -> ProjectList:
    """Return projects from the DB (empty list is valid until Phase 2 loads data)."""
    filters = []
    if state:
        # geography filter = where the work is LOCATED (work_state), the same meaning as GET /risk-scores?state=.
        # (Project.state is the MP's state.) The user's scope is ANDed on afterwards: a filter only narrows.
        filters.append(func.upper(Project.work_state) == state.upper())
    if district:
        filters.append(Project.district == district)

    total = db.scalar(scope_project_query(select(func.count()).select_from(Project).where(*filters), user)) or 0
    stmt = select(Project).where(*filters).order_by(Project.id).limit(limit).offset(offset)
    rows = db.scalars(scope_project_query(stmt, user)).all()
    return ProjectList(total=total, items=[ProjectOut.model_validate(r) for r in rows])


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(project_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> ProjectDetail:
    """Full project detail + the complete ordered risk explanation list."""
    row = db.get(Project, project_id)
    assert_project_scope(row, user)

    rf = db.scalar(select(RiskFlag).where(RiskFlag.project_id == project_id))

    detail = ProjectDetail.model_validate(row)
    detail.amount = row.sanctioned_amount or row.final_amount
    if rf is not None:
        detail.combined_risk_score = rf.combined_risk_score
        detail.rule_score = rf.rule_score
        detail.ml_score = rf.ml_score
        detail.ml_anomaly_score = rf.ml_anomaly_score
        detail.severity = severity_band(rf.combined_risk_score)
        detail.rule_flags = rf.rule_flags
        detail.flagged_at = rf.flagged_at
        detail.first_flagged_at = db.scalar(
            text("SELECT min(timestamp) FROM audit_log WHERE project_id = :p AND event_type = 'risk_score'"),
            {"p": project_id},
        ) or rf.flagged_at
        detail.explanation = [
            ExplanationItem(**e) for e in (rf.explanation or []) if isinstance(e, dict)
        ]

    cr = db.scalar(select(CaseReview).where(CaseReview.project_id == project_id))
    if cr is not None:
        detail.case_status = cr.status
        detail.case_note = cr.note
        detail.case_updated_at = cr.updated_at
    return detail
