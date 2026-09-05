from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Project
from app.schemas import ProjectList, ProjectOut

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=ProjectList)
def list_projects(
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    state: str | None = None,
    district: str | None = None,
) -> ProjectList:
    """Return projects from the DB (empty list is valid until Phase 2 loads data)."""
    filters = []
    if state:
        filters.append(Project.state == state)
    if district:
        filters.append(Project.district == district)

    total = db.scalar(select(func.count()).select_from(Project).where(*filters)) or 0
    rows = db.scalars(
        select(Project)
        .where(*filters)
        .order_by(Project.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return ProjectList(total=total, items=[ProjectOut.model_validate(r) for r in rows])


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)) -> ProjectOut:
    row = db.get(Project, project_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectOut.model_validate(row)
