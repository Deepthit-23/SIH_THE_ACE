from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Project(Base):
    """A single MPLAD works record.

    Populated from BOTH source populations (they do NOT join reliably on Work ID):
      - recommended works  -> status='recommended', sanctioned_amount set
      - completed works    -> status='completed',   final_amount set
    """

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Work ID from source. NOT unique -- IDs collide across the two populations.
    external_id: Mapped[str | None] = mapped_column(String(64), index=True)
    source_file: Mapped[str | None] = mapped_column(String(64), index=True)

    mp_name: Mapped[str | None] = mapped_column(String(255), index=True)
    constituency: Mapped[str | None] = mapped_column(String(255))
    state: Mapped[str | None] = mapped_column(String(128), index=True)
    # Best-effort district, parsed from the IDA code prefix (uppercased). Nullable.
    district: Mapped[str | None] = mapped_column(String(128), index=True)
    # State the WORK is located in (`state` is the MP's state). Derived by pipeline/location.py; NULL
    # (= "same as state") until it has run. District scoping uses (work_state, district), never the name alone.
    work_state: Mapped[str | None] = mapped_column(String(128), index=True)
    # how work_state was derived: home | cross_state | only_state | unresolved | no_district | unlocated (the last three: work_state NULL)
    location_method: Mapped[str | None] = mapped_column(String(16))
    ida: Mapped[str | None] = mapped_column(String(255))
    house: Mapped[str | None] = mapped_column(String(32), index=True)
    is_rajya_sabha: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )

    # Source category field -- near-constant "Normal/Others", kept for reference.
    category: Mapped[str | None] = mapped_column(String(128))
    # Keyword-derived bucket from work_description -- the real grouping key.
    derived_category: Mapped[str | None] = mapped_column(String(64), index=True)
    work_description: Mapped[str | None] = mapped_column(String, default=None)

    sanctioned_amount: Mapped[float | None] = mapped_column(Numeric(16, 2))  # recommended
    final_amount: Mapped[float | None] = mapped_column(Numeric(16, 2))       # completed
    spent_amount: Mapped[float | None] = mapped_column(Numeric(16, 2))       # n/a at work level

    contractor_name: Mapped[str | None] = mapped_column(String(255), index=True)  # n/a

    start_date: Mapped[date | None] = mapped_column(Date)             # n/a in source
    recommendation_date: Mapped[date | None] = mapped_column(Date)    # recommended
    completion_date: Mapped[date | None] = mapped_column(Date)        # completed
    status: Mapped[str | None] = mapped_column(String(64), index=True)  # recommended|completed

    has_images: Mapped[bool | None] = mapped_column(Boolean)
    average_rating: Mapped[float | None] = mapped_column(Float)  # completed only

    # --- Internal-only anomaly labels. NEVER exposed via API/UI. ---
    is_synthetic_anomaly: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    anomaly_type: Mapped[str | None] = mapped_column(String(64))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    risk_flag: Mapped["RiskFlag | None"] = relationship(
        back_populates="project", uselist=False, cascade="all, delete-orphan"
    )


class VendorTransaction(Base):
    """Vendor-level expenditure transactions.

    NOT foreign-keyed to `projects` -- the source has no Work ID, so there is no
    reliable join. This is the basis for contractor-concentration and
    payment-gap analysis.
    """

    __tablename__ = "vendor_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    mp_name: Mapped[str | None] = mapped_column(String(255), index=True)
    constituency: Mapped[str | None] = mapped_column(String(255), index=True)
    state: Mapped[str | None] = mapped_column(String(128), index=True)
    house: Mapped[str | None] = mapped_column(String(32))
    work_description: Mapped[str | None] = mapped_column(String)

    vendor: Mapped[str | None] = mapped_column(String(255), index=True)
    ida: Mapped[str | None] = mapped_column(String(255))
    district: Mapped[str | None] = mapped_column(String(128), index=True)
    # State the WORK is located in (`state` is the MP's state). Derived by pipeline/location.py; NULL
    # (= "same as state") until it has run. District scoping uses (work_state, district), never the name alone.
    work_state: Mapped[str | None] = mapped_column(String(128), index=True)
    location_method: Mapped[str | None] = mapped_column(String(16))

    amount: Mapped[float | None] = mapped_column(Numeric(16, 2))
    expenditure_date: Mapped[date | None] = mapped_column(Date)
    payment_status: Mapped[str | None] = mapped_column(String(64), index=True)

    # Internal-only. NEVER exposed via API/UI.
    is_synthetic_anomaly: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    anomaly_type: Mapped[str | None] = mapped_column(String(64))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MpSummary(Base):
    """Per-MP aggregates from the MP summary export (774 rows)."""

    __tablename__ = "mp_summary"

    id: Mapped[int] = mapped_column(primary_key=True)
    mp_name: Mapped[str | None] = mapped_column(String(255), index=True)
    constituency: Mapped[str | None] = mapped_column(String(255))
    state: Mapped[str | None] = mapped_column(String(128), index=True)
    house: Mapped[str | None] = mapped_column(String(32))

    allocated_amount: Mapped[float | None] = mapped_column(Numeric(18, 2))
    amount_recommended: Mapped[float | None] = mapped_column(Numeric(18, 2))
    total_expenditure: Mapped[float | None] = mapped_column(Numeric(18, 2))
    utilization_pct: Mapped[float | None] = mapped_column(Float)
    completed_works: Mapped[int | None] = mapped_column(Integer)
    recommended_works: Mapped[int | None] = mapped_column(Integer)
    completion_rate_pct: Mapped[float | None] = mapped_column(Float)
    balance_unpaid: Mapped[float | None] = mapped_column(Numeric(18, 2))
    transaction_count: Mapped[int | None] = mapped_column(Integer)
    successful_payments: Mapped[int | None] = mapped_column(Integer)
    pending_payments: Mapped[int | None] = mapped_column(Integer)
    average_rating: Mapped[float | None] = mapped_column(Float)  # "N/A" -> NULL

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MpAllocation(Base):
    """Official SIH allocation ceiling extracted from the supplied PDFs.

    This is deliberately separate from ``mp_summary.allocated_amount``: the
    latter is sourced from empoweredindian.in's MPLADS export and is used only
    for reconciliation, never as a replacement for this official ceiling.
    """
    __tablename__ = "mp_allocation"
    id: Mapped[int] = mapped_column(primary_key=True)
    mp_name: Mapped[str] = mapped_column(String(255), index=True)
    state: Mapped[str | None] = mapped_column(String(128), index=True)
    house: Mapped[str] = mapped_column(String(32), index=True)
    constituency: Mapped[str | None] = mapped_column(String(255))
    is_nominated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    term_start: Mapped[int | None] = mapped_column(Integer)
    term_end: Mapped[int | None] = mapped_column(Integer)
    # One official Lok Sabha source row has no published amount; preserve the
    # row and make downstream ceiling checks explicitly non-applicable.
    official_allocated_ceiling: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)


class User(Base):
    """Prototype accounts. Password hashes only; plaintext credentials are never stored."""
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    scope_value: Mapped[str | None] = mapped_column(String(255))
    # District Authority accounts are scoped by the (state, district) PAIR: district names repeat across
    # states. scope_state is that state; a district user without one sees nothing (fails closed).
    scope_state: Mapped[str | None] = mapped_column(String(255))
    # Provisioning state (Ministry user management). Existing rows default to active / no forced change,
    # so the seeded demo accounts keep working. Added to old databases by auth.ensure_user_columns().
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RiskFlag(Base):
    """Computed risk assessment for a project (rule engine + ML combined)."""

    __tablename__ = "risk_flags"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), unique=True, index=True
    )

    rule_flags: Mapped[dict | None] = mapped_column(JSONB)
    rule_score: Mapped[float | None] = mapped_column(Float)   # 0-100, sum of triggered rule points
    ml_score: Mapped[float | None] = mapped_column(Float)     # 0-100, ML contribution
    ml_anomaly_score: Mapped[float | None] = mapped_column(Float)
    combined_risk_score: Mapped[float | None] = mapped_column(Float, index=True)
    # List of {"source": "rule"|"ml", "code": str, "message": str}
    explanation: Mapped[list | dict | None] = mapped_column(JSONB)

    flagged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    project: Mapped["Project"] = relationship(back_populates="risk_flag")


class CaseReview(Base):
    """Auditor workflow state for a project (one row = current state).

    A project with no row here is implicitly `pending`. Every change also appends
    a `case_review` entry to `audit_log` (same hash-chain as scoring events).
    """

    __tablename__ = "case_reviews"

    STATUSES = ("pending", "under_review", "confirmed", "dismissed")

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), unique=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    note: Mapped[str | None] = mapped_column(String)          # dismissal reason, etc.
    reviewer: Mapped[str | None] = mapped_column(String(128))  # no auth -> free text
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AuditLog(Base):
    """Hash-chained, tamper-evident record of scoring events (Phase 6).

    Deliberately simplified demonstration of tamper-evidence -- NOT a real
    distributed ledger / blockchain.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[int | None] = mapped_column(Integer, index=True)
    # Canonical payload that was hashed (project_id, score, explanation digest, ts).
    payload: Mapped[dict | None] = mapped_column(JSONB)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
