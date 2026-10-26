"""
api/schemas/admin.py
--------------------
Pydantic models for analyst / admin API payloads.

Models:
    AlertResponse    : id, txn_id, status, reasons (list[str]),
                       risk_score (float — analyst-visible), reviewed_at, notes
                       — UPI IDs are masked by default (DESIGN.md §2.7).
    ResolveRequest   : action (Enum: "APPROVED" | "CONFIRMED_FRAUD" | "ESCALATED"),
                       notes (str, optional)
    ConfigResponse   : thresholds (dict), feature_toggles (dict)
    ConfigUpdateRequest : thresholds (dict, optional), feature_toggles (dict, optional)
    RuleIn           : name, condition_json, action, enabled
    RuleOut          : id, name, condition_json, action, enabled
    MetricsResponse  : alerts_per_day (list), review_outcome_counts (dict)
    AuditLogEntry    : id, actor_id, action, target, before_json, after_json, ts
    GraphResponse    : nodes (list[dict]), edges (list[dict])
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel


# ── Alerts ────────────────────────────────────────────────────────────────────

class AlertResponse(BaseModel):
    id: int
    txn_id: int
    status: str
    reasons: list[str]
    risk_score: float | None        # analyst-visible raw score
    reviewed_at: datetime | None
    notes: str | None
    # Transaction fields (masked for analyst)
    amount: Decimal | None = None
    masked_sender_upi: str | None = None
    masked_receiver_upi: str | None = None
    decision: str | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class ResolveRequest(BaseModel):
    action: Literal["APPROVED", "CONFIRMED_FRAUD", "ESCALATED"]
    notes: str | None = None


class ResolveResponse(BaseModel):
    alert_id: int
    status: str
    message: str


# ── Transactions ──────────────────────────────────────────────────────────────

class AdminTransactionOut(BaseModel):
    id: int
    amount: Decimal
    masked_sender_upi: str
    masked_receiver_upi: str
    city: str
    ip: str
    created_at: datetime
    status: str
    decision: str | None
    risk_score: float | None
    is_synthetic: bool

    model_config = {"from_attributes": True}


# ── Config ────────────────────────────────────────────────────────────────────

class ConfigResponse(BaseModel):
    thresholds: dict[str, float]
    feature_toggles: dict[str, bool]


class ConfigUpdateRequest(BaseModel):
    thresholds: dict[str, float] | None = None
    feature_toggles: dict[str, bool] | None = None


# ── Rules ─────────────────────────────────────────────────────────────────────

class RuleIn(BaseModel):
    name: str
    condition_json: dict[str, Any]
    action: Literal["ALLOW", "STEP_UP", "HOLD"]
    enabled: bool = True


class RuleOut(BaseModel):
    id: int
    name: str
    condition_json: dict[str, Any]
    action: str
    enabled: bool

    model_config = {"from_attributes": True}


# ── Metrics ───────────────────────────────────────────────────────────────────

class MetricsResponse(BaseModel):
    alerts_per_day: list[dict[str, Any]]
    review_outcome_counts: dict[str, int]
    total_transactions: int
    total_held: int


# ── Audit log ─────────────────────────────────────────────────────────────────

class AuditLogEntry(BaseModel):
    id: int
    actor_id: int | None
    action: str
    target: str
    before_json: dict | None
    after_json: dict | None
    ts: datetime

    model_config = {"from_attributes": True}


# ── Graph ─────────────────────────────────────────────────────────────────────

class GraphResponse(BaseModel):
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
