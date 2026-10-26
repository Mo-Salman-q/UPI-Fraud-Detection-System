"""
api/models/alert.py
-------------------
SQLAlchemy ORM model for the `alerts` table.

Schema (DESIGN.md §2.1):
    id           : Integer primary key
    txn_id       : ForeignKey → transactions.id (unique; one alert per held txn)
    status       : Enum("OPEN", "APPROVED", "CONFIRMED_FRAUD", "ESCALATED")
    reviewer_id  : ForeignKey → users.id (nullable until reviewed)
    reasons_json : JSON — list of human-readable explanation strings from explain_service
    reviewed_at  : DateTime (nullable)
    notes        : Text (analyst free-text notes)

Index: (status) — for the alert queue filter query.

Lifecycle (DESIGN.md §2.3):
    Created by payment_service when decision == HOLD.
    Resolved by POST /admin/alerts/{id}/resolve.
    Outcome stored as a label for future retraining.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.models.base import Base


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    txn_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("transactions.id"), unique=True, nullable=False
    )
    status: Mapped[str] = mapped_column(
        Enum("OPEN", "APPROVED", "CONFIRMED_FRAUD", "ESCALATED", name="alert_status"),
        nullable=False,
        default="OPEN",
    )
    reviewer_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    transaction: Mapped["Transaction"] = relationship("Transaction", back_populates="alert")
    reviewer: Mapped["User"] = relationship("User", foreign_keys=[reviewer_id])

    __table_args__ = (Index("ix_alerts_status", "status"),)

    def __repr__(self) -> str:
        return f"<Alert id={self.id} txn_id={self.txn_id} status={self.status!r}>"
