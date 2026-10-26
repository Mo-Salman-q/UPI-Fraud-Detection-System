"""
api/schemas/__init__.py
-----------------------
Package marker for the `api.schemas` sub-package (Pydantic request/response models).

Re-export all schemas here for convenient importing:
    from api.schemas import PaymentRequest, PaymentResponse, AlertResponse, …
"""

from api.schemas.auth import LoginRequest, TokenResponse  # noqa: F401
from api.schemas.payment import (  # noqa: F401
    PaymentRequest,
    PaymentResponse,
    ConfirmResponse,
    TransactionSummary,
)
from api.schemas.admin import (  # noqa: F401
    AlertResponse,
    ResolveRequest,
    ResolveResponse,
    ConfigResponse,
    ConfigUpdateRequest,
    RuleIn,
    RuleOut,
    MetricsResponse,
    AuditLogEntry,
    GraphResponse,
    AdminTransactionOut,
)

__all__ = [
    "LoginRequest",
    "TokenResponse",
    "PaymentRequest",
    "PaymentResponse",
    "ConfirmResponse",
    "TransactionSummary",
    "AlertResponse",
    "ResolveRequest",
    "ResolveResponse",
    "ConfigResponse",
    "ConfigUpdateRequest",
    "RuleIn",
    "RuleOut",
    "MetricsResponse",
    "AuditLogEntry",
    "GraphResponse",
    "AdminTransactionOut",
]
