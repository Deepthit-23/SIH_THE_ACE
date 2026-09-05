from datetime import date, datetime

from sqlalchemy import (
    DateTime,
    Date,
    ForeignKey,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Project(Base):
    """A single MPLAD-funded works project."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Identifier from the source dataset (mplads.gov.in export), if any.
    external_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)

    mp_name: Mapped[str | None] = mapped_column(String(255), index=True)
    constituency: Mapped[str | None] = mapped_column(String(255))
    state: Mapped[str | None] = mapped_column(String(128), index=True)
    district: Mapped[str | None] = mapped_column(String(128), index=True)
    category: Mapped[str | None] = mapped_column(String(128), index=True)

    sanctioned_amount: Mapped[float | None] = mapped_column(Numeric(16, 2))
    spent_amount: Mapped[float | None] = mapped_column(Numeric(16, 2))

    contractor_name: Mapped[str | None] = mapped_column(String(255), index=True)

    start_date: Mapped[date | None] = mapped_column(Date)
    completion_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str | None] = mapped_column(String(64), index=True)

    # --- Internal-only anomaly labels (Phase 2). NEVER exposed via API/UI. ---
    is_synthetic_anomaly: Mapped[bool] = mapped_column(default=False, nullable=False)
    anomaly_type: Mapped[str | None] = mapped_column(String(64))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    risk_flag: Mapped["RiskFlag | None"] = relationship(
        back_populates="project", uselist=False, cascade="all, delete-orphan"
    )


class RiskFlag(Base):
    """Computed risk assessment for a project (rule engine + ML combined)."""

    __tablename__ = "risk_flags"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), unique=True, index=True
    )

    # Which rules fired, e.g. {"cost_anomaly": true, "timeline_anomaly": false, ...}
    rule_flags: Mapped[dict | None] = mapped_column(JSONB)
    ml_anomaly_score: Mapped[float | None] = mapped_column()
    combined_risk_score: Mapped[float | None] = mapped_column(index=True)
    # List of {"source": "rule"|"ml", "code": str, "message": str}
    explanation: Mapped[list | dict | None] = mapped_column(JSONB)

    flagged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    project: Mapped["Project"] = relationship(back_populates="risk_flag")


class AuditLog(Base):
    """Hash-chained, tamper-evident record of scoring events (Phase 6).

    This is a deliberately simplified demonstration of the tamper-evidence
    concept -- NOT a real distributed ledger / blockchain.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
