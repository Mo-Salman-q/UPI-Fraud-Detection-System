"""
api/models/account.py
---------------------
SQLAlchemy ORM model for the `accounts` table.

Schema (DESIGN.md §2.1):
    id         : Integer primary key
    user_id    : ForeignKey → users.id
    balance    : Numeric(18, 2) — current balance in INR (rupees)
    is_frozen  : Boolean, default False — frozen accounts cannot send payments

Business rules enforced in payment_service:
    - A payment is rejected if sender's balance < amount.
    - Balance is only decremented for ALLOW decisions (DESIGN.md §2.3).
    - is_frozen=True blocks all outgoing payments regardless of risk score.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.models.base import Base


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("50000.00"))
    is_frozen: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    user: Mapped["User"] = relationship("User", back_populates="accounts")

    def __repr__(self) -> str:
        return f"<Account id={self.id} user_id={self.user_id} balance={self.balance}>"
