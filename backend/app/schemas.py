from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ProjectOut(BaseModel):
    """Public representation of a project.

    NOTE: `is_synthetic_anomaly` / `anomaly_type` are intentionally omitted --
    those are internal evaluation labels and must never leave the backend.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: str | None = None
    mp_name: str | None = None
    constituency: str | None = None
    state: str | None = None
    district: str | None = None
    category: str | None = None
    sanctioned_amount: Decimal | None = None
    spent_amount: Decimal | None = None
    contractor_name: str | None = None
    start_date: date | None = None
    completion_date: date | None = None
    status: str | None = None
    created_at: datetime


class ProjectList(BaseModel):
    total: int
    items: list[ProjectOut]


class HealthOut(BaseModel):
    status: str
    database: str
