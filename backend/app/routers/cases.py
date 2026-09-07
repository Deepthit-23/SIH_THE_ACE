"""Auditor case-management workflow.

A project's review state lives in `case_reviews` (one row = current state; no row
= implicitly `pending`). Every change also appends a `case_review` entry to the
`audit_log` hash-chain, so review decisions are as tamper-evident as scores.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app import audit
from app.database import get_db
from app.models import CaseReview, Project
from app.schemas import (
    CaseHistoryItem,
    CaseListItem,
    CaseListPage,
    CaseReviewOut,
    CaseUpdateIn,
    severity_band,
)

router = APIRouter(tags=["cases"])


def _default(project_id: int) -> CaseReviewOut:
    return CaseReviewOut(project_id=project_id, status="pending")


@router.get("/projects/{project_id}/case", response_model=CaseReviewOut)
def get_case(project_id: int, db: Session = Depends(get_db)) -> CaseReviewOut:
    cr = db.scalar(select(CaseReview).where(CaseReview.project_id == project_id))
    return CaseReviewOut.model_validate(cr) if cr else _default(project_id)


@router.put("/projects/{project_id}/case", response_model=CaseReviewOut)
def set_case(
    project_id: int, body: CaseUpdateIn, db: Session = Depends(get_db)
) -> CaseReviewOut:
    if body.status not in CaseReview.STATUSES:
        raise HTTPException(422, f"status must be one of {list(CaseReview.STATUSES)}")
    note = (body.note or "").strip() or None
    if body.status == "dismissed" and not note:
        raise HTTPException(422, "a note explaining the dismissal is required")
    if db.get(Project, project_id) is None:
        raise HTTPException(404, "Project not found")

    cr = db.scalar(select(CaseReview).where(CaseReview.project_id == project_id))
    if cr is None:
        cr = CaseReview(project_id=project_id)
        db.add(cr)
    cr.status = body.status
    cr.note = note
    cr.reviewer = (body.reviewer or "").strip() or None
    db.flush()

    ts = datetime.now(timezone.utc)
    audit.append_case_event(db, project_id, cr.status, cr.note, cr.reviewer, ts)
    db.commit()
    db.refresh(cr)
    return CaseReviewOut.model_validate(cr)


@router.get("/projects/{project_id}/case/history", response_model=list[CaseHistoryItem])
def case_history(project_id: int, db: Session = Depends(get_db)) -> list[CaseHistoryItem]:
    rows = db.execute(
        text(
            """
            SELECT payload, payload_hash FROM audit_log
            WHERE event_type = 'case_review' AND project_id = :pid
            ORDER BY id
            """
        ),
        {"pid": project_id},
    ).all()
    return [
        CaseHistoryItem(
            status=r.payload.get("status", "?"),
            reviewer=r.payload.get("reviewer") or None,
            note_sha256=r.payload.get("note_sha256", ""),
            timestamp=r.payload.get("timestamp", ""),
            payload_hash=r.payload_hash,
        )
        for r in rows
    ]


@router.get("/cases", response_model=CaseListPage)
def list_cases(
    db: Session = Depends(get_db),
    status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> CaseListPage:
    """All projects an auditor has acted on, newest first."""
    filters = ["1=1"]
    params: dict = {"lim": limit, "off": offset}
    if status:
        filters.append("cr.status = :status")
        params["status"] = status

    where = " AND ".join(filters)
    total = db.execute(
        text(f"SELECT count(*) FROM case_reviews cr WHERE {where}"), params
    ).scalar_one()
    rows = db.execute(
        text(
            f"""
            SELECT cr.project_id, cr.status, cr.note, cr.reviewer, cr.updated_at,
                   p.work_description, p.mp_name, rf.combined_risk_score
            FROM case_reviews cr
            JOIN projects p ON p.id = cr.project_id
            LEFT JOIN risk_flags rf ON rf.project_id = cr.project_id
            WHERE {where}
            ORDER BY cr.updated_at DESC
            LIMIT :lim OFFSET :off
            """
        ),
        params,
    ).all()
    return CaseListPage(
        total=total,
        items=[
            CaseListItem(
                project_id=r.project_id,
                status=r.status,
                note=r.note,
                reviewer=r.reviewer,
                updated_at=r.updated_at,
                work_description=r.work_description,
                mp_name=r.mp_name,
                combined_risk_score=r.combined_risk_score,
                severity=severity_band(r.combined_risk_score),
            )
            for r in rows
        ],
    )
