"""
api/models/device.py
--------------------
SQLAlchemy ORM model for the `devices` table.

Schema (DESIGN.md §2.1):
    id                 : Integer primary key
    user_id            : ForeignKey → users.id
    device_fingerprint : String — client-supplied identifier (e.g. browser hash)
    first_seen         : DateTime
    last_seen          : DateTime — updated on each use

Used by feature_service to compute:
    is_new_device : True if device_fingerprint has never appeared for this user
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.models.base import Base


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    device_fingerprint: Mapped[str] = mapped_column(String(256), nullable=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="devices")

    def __repr__(self) -> str:
        return f"<Device id={self.id} user_id={self.user_id} fp={self.device_fingerprint!r}>"
