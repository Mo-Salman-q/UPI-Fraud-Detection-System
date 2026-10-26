"""
api/models/user.py
------------------
SQLAlchemy ORM model for the `users` table.

Schema (DESIGN.md §2.1):
    id           : Integer primary key
    name         : String — display name
    upi_id       : String, unique — used as login username (e.g. "alice@sentinel")
    password_hash: String — bcrypt hash via passlib
    role         : Enum("customer", "analyst", "admin")
    created_at   : DateTime, server default = now()

Relationships:
    accounts     : one-to-many → Account
    devices      : one-to-many → Device
    sent_txns    : one-to-many → Transaction (as sender)
    received_txns: one-to-many → Transaction (as receiver)
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.models.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    upi_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(
        Enum("customer", "analyst", "admin", name="user_role"),
        nullable=False,
        default="customer",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    # Relationships (back-populated in child models)
    accounts: Mapped[list] = relationship("Account", back_populates="user", lazy="select")
    devices: Mapped[list] = relationship("Device", back_populates="user", lazy="select")
    sent_txns: Mapped[list] = relationship(
        "Transaction", foreign_keys="Transaction.sender_id", back_populates="sender", lazy="select"
    )
    received_txns: Mapped[list] = relationship(
        "Transaction",
        foreign_keys="Transaction.receiver_id",
        back_populates="receiver",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} upi_id={self.upi_id!r} role={self.role!r}>"
