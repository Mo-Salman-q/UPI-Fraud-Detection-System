"""
api/models/rule.py
------------------
SQLAlchemy ORM model for the `rules` table.

Schema (DESIGN.md §2.1):
    id             : Integer primary key
    name           : String — human-readable label
    condition_json : JSON — structured predicate evaluated by rules_engine
    action         : Enum("ALLOW", "STEP_UP", "HOLD") — forced decision on match
    enabled        : Boolean — disable without deleting

condition_json example:
    {"feature": "is_new_payee", "op": "eq", "value": true,
     "and": {"feature": "amount", "op": "gt", "value": 10000}}

Rules are evaluated in ascending id order; first match wins.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Enum, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import Base


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    condition_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    action: Mapped[str] = mapped_column(
        Enum("ALLOW", "STEP_UP", "HOLD", name="rule_action"),
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return f"<Rule id={self.id} name={self.name!r} action={self.action!r} enabled={self.enabled}>"
