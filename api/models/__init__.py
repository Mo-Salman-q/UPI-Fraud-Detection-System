"""
api/models/__init__.py
----------------------
Package marker for the `api.models` sub-package (SQLAlchemy ORM models).
Import all ORM classes here so Alembic / create_all() can discover them.
"""

from api.models.base import Base  # noqa: F401 — must come first
from api.models.user import User  # noqa: F401
from api.models.account import Account  # noqa: F401
from api.models.device import Device  # noqa: F401
from api.models.transaction import Transaction  # noqa: F401
from api.models.alert import Alert  # noqa: F401
from api.models.config import Config  # noqa: F401
from api.models.rule import Rule  # noqa: F401
from api.models.audit_log import AuditLog  # noqa: F401

__all__ = [
    "Base",
    "User",
    "Account",
    "Device",
    "Transaction",
    "Alert",
    "Config",
    "Rule",
    "AuditLog",
]
