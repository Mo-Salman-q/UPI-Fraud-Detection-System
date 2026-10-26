"""
api/models/audit_log.py
------------------------
SQLAlchemy ORM model for the `audit_log` table.

Schema (DESIGN.md §2.1):
    id          : Integer primary key
    actor_id    : ForeignKey → users.id — who performed the action
    action      : String — e.g. "ALERT_RESOLVED", "CONFIG_UPDATED", "RULE_CREATED"
    target      : String — e.g. "alert:42", "config:thresholds"
    before_json : JSON (nullable) — state before the change
    after_json  : JSON (nullable) — state after the change
    ts          : DateTime, server default = now()

Immutability: rows in this table are never updated or deleted.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    actor_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target: Mapped[str] = mapped_column(String(256), nullable=False)
    before_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False, index=True
    )

    def __repr__(self) -> str:
        return f"<AuditLog id={self.id} action={self.action!r} target={self.target!r}>"
