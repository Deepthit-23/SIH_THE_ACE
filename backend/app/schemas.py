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
    source_file: str | None = None
    mp_name: str | None = None
    constituency: str | None = None
    state: str | None = None
    district: str | None = None
    house: str | None = None
    is_rajya_sabha: bool = False
    category: str | None = None
    derived_category: str | None = None
    work_description: str | None = None
    sanctioned_amount: Decimal | None = None
    final_amount: Decimal | None = None
    spent_amount: Decimal | None = None
    contractor_name: str | None = None
    start_date: date | None = None
    recommendation_date: date | None = None
    completion_date: date | None = None
    status: str | None = None
    has_images: bool | None = None
    average_rating: float | None = None
    created_at: datetime


class ProjectList(BaseModel):
    total: int
    items: list[ProjectOut]


class HealthOut(BaseModel):
    status: str
    database: str


class AuditVerifyOut(BaseModel):
    valid: bool
    entries_checked: int
    broken_at: int | None = None
    cached: bool = False
    checked_at: str | None = None


# --------------------------------------------------------------------------- #
# Risk scoring
# --------------------------------------------------------------------------- #
def severity_band(score: float | None) -> str:
    """Score bands used across API + UI. ~46% of real projects score 0."""
    if score is None:
        return "unscored"
    if score >= 70:
        return "high"
    if score >= 50:
        return "medium"
    if score > 0:
        return "low"
    return "none"


class ExplanationItem(BaseModel):
    source: str          # "rule" | "ml"
    code: str
    label: str
    weight: float
    message: str


class RiskListItem(BaseModel):
    """Light row for the ranked list -- only the top reasons, not the full list."""

    id: int
    external_id: str | None = None
    work_description: str | None = None
    mp_name: str | None = None
    constituency: str | None = None
    state: str | None = None
    district: str | None = None
    derived_category: str | None = None
    status: str | None = None
    amount: Decimal | None = None                # coalesced sanctioned/final
    combined_risk_score: float | None = None
    severity: str
    case_status: str = "pending"
    top_reasons: list[str] = []


class RiskListPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[RiskListItem]


class ProjectDetail(ProjectOut):
    """Full project + its complete risk assessment."""

    amount: Decimal | None = None
    combined_risk_score: float | None = None
    rule_score: float | None = None
    ml_score: float | None = None
    ml_anomaly_score: float | None = None
    severity: str = "unscored"
    rule_flags: dict | None = None
    explanation: list[ExplanationItem] = []
    case_status: str = "pending"
    case_note: str | None = None
    case_updated_at: datetime | None = None


class CaseUpdateIn(BaseModel):
    status: str
    note: str | None = None
    reviewer: str | None = None


class CaseReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: int
    status: str
    note: str | None = None
    reviewer: str | None = None
    updated_at: datetime | None = None


class CaseHistoryItem(BaseModel):
    status: str
    reviewer: str | None = None
    note_sha256: str
    timestamp: str
    payload_hash: str


class CaseListItem(BaseModel):
    project_id: int
    status: str
    note: str | None = None
    reviewer: str | None = None
    updated_at: datetime | None = None
    work_description: str | None = None
    mp_name: str | None = None
    combined_risk_score: float | None = None
    severity: str


class CaseListPage(BaseModel):
    total: int
    items: list[CaseListItem]


class ContractorUnitShare(BaseModel):
    mp_name: str | None = None
    constituency: str | None = None
    txn_count: int
    txn_value: float
    share_of_unit_count: float
    share_of_unit_value: float
    concentration_flagged: bool


class ContractorPattern(BaseModel):
    vendor: str
    total_txn_count: int
    total_txn_value: float
    flagged_txn_count: int          # txns in units where this vendor is over-concentrated
    unit_count: int
    max_share_of_unit_value: float
    max_share_of_unit_count: float
    units: list[ContractorUnitShare]


class DistrictCategoryStat(BaseModel):
    derived_category: str
    project_count: int
    avg_risk_score: float


class DistrictPattern(BaseModel):
    district: str
    project_count: int
    avg_risk_score: float
    high_risk_count: int            # >= threshold
    threshold: float
    categories: list[DistrictCategoryStat]


class PatternRankRow(BaseModel):
    key: str                        # district name or vendor name
    project_count: int | None = None
    txn_count: int | None = None
    avg_risk_score: float | None = None
    high_risk_count: int | None = None
    max_share_of_unit_value: float | None = None
    flagged_txn_count: int | None = None


class PatternRankList(BaseModel):
    dimension: str                  # "district" | "contractor"
    items: list[PatternRankRow]
