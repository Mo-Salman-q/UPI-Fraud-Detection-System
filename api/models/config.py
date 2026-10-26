"""
api/models/config.py
--------------------
SQLAlchemy ORM model for the `config` table.

Schema (DESIGN.md §2.1):
    key        : String primary key — e.g. "thresholds", "feature_toggles"
    value_json : JSON — arbitrary config payload
    updated_by : ForeignKey → users.id (admin who last changed this entry)
    updated_at : DateTime

Well-known keys:
    "thresholds"      : {"T_hold": 0.70, "T_step": 0.30}
    "feature_toggles" : {"use_network_features": true, "use_device_features": true}

Audit requirement (DESIGN.md §2.7):
    Every PUT /admin/config call must record before/after in audit_log
    via audit_service.log_action().
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import Base


class Config(Base):
    __tablename__ = "config"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Config key={self.key!r}>"
