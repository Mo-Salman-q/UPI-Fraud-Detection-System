"""
api/models/transaction.py
--------------------------
SQLAlchemy ORM model for the `transactions` table.

Schema (DESIGN.md §2.1):
    id            : Integer primary key
    sender_id     : ForeignKey → users.id
    receiver_id   : ForeignKey → users.id
    amount        : Numeric(18, 2)
    device_id     : ForeignKey → devices.id (nullable)
    ip            : String
    city          : String
    created_at    : DateTime
    status        : Enum("PENDING_CONFIRM", "COMPLETED", "HELD", "FAILED")
    risk_score    : Float (model output; stored for audit, never returned to customer)
    decision      : Enum("ALLOW", "STEP_UP", "HOLD")
    model_version : String — e.g. "sentinel_v1"
    features_json : JSON — snapshot of the feature dict at decision time
    is_synthetic  : Boolean — True for demo-generated transactions

Indexes (DESIGN.md §2.1):
    (sender_id, created_at)   — velocity / history queries
    (receiver_id, created_at) — network / in-degree queries
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.models.base import Base


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    sender_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    receiver_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    device_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("devices.id"), nullable=True)
    ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    city: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    status: Mapped[str] = mapped_column(
        Enum("PENDING_CONFIRM", "COMPLETED", "HELD", "FAILED", name="txn_status"),
        nullable=False,
        default="PENDING_CONFIRM",
    )
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    decision: Mapped[str | None] = mapped_column(
        Enum("ALLOW", "STEP_UP", "HOLD", name="txn_decision"),
        nullable=True,
    )
    model_version: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    features_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Relationships
    sender: Mapped["User"] = relationship(
        "User", foreign_keys=[sender_id], back_populates="sent_txns"
    )
    receiver: Mapped["User"] = relationship(
        "User", foreign_keys=[receiver_id], back_populates="received_txns"
    )
    device: Mapped["Device"] = relationship("Device", foreign_keys=[device_id])
    alert: Mapped["Alert"] = relationship("Alert", back_populates="transaction", uselist=False)

    # Composite indexes for velocity and network queries
    __table_args__ = (
        Index("ix_transactions_sender_created", "sender_id", "created_at"),
        Index("ix_transactions_receiver_created", "receiver_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Transaction id={self.id} amount={self.amount} decision={self.decision!r}>"
