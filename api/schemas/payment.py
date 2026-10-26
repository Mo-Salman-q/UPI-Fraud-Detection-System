"""
api/schemas/payment.py
-----------------------
Pydantic models for customer-facing payment API payloads.

Models:
    PaymentRequest   : receiver_upi (str), amount (Decimal > 0), device_id (str),
                       ip (str), city (str)
    PaymentResponse  : txn_id (int), status (str), decision (str),
                       risk_band ("low" | "medium" | "high"), message (str)
                       — NEVER includes raw risk_score or SHAP values.
    ConfirmResponse  : txn_id (int), status (str), message (str)
    TransactionSummary : id, amount, receiver_upi, city, created_at, status, decision

Security note (DESIGN.md §2.7):
    PaymentResponse must not expose model outputs beyond risk_band.
    risk_band is a coarse label derived from the decision, not a raw probability.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class PaymentRequest(BaseModel):
    receiver_upi: str = Field(..., description="UPI ID of the payee")
    amount: Decimal = Field(..., gt=0, description="Amount in INR (must be > 0)")
    device_id: str = Field(default="", description="Client device fingerprint")
    ip: str = Field(default="", description="Client IP address")
    city: str = Field(default="", description="City from client context")


class PaymentResponse(BaseModel):
    txn_id: int
    status: str  # "COMPLETED" | "PENDING_CONFIRM" | "HELD"
    decision: str  # "ALLOW" | "STEP_UP" | "HOLD"
    risk_band: Literal["low", "medium", "high"]
    message: str
    # NOTE: risk_score is intentionally absent — customers never see it.


class ConfirmResponse(BaseModel):
    txn_id: int
    status: str
    decision: str
    risk_band: Literal["low", "medium", "high"]
    message: str


class TransactionSummary(BaseModel):
    id: int
    amount: Decimal
    receiver_upi: str
    city: str
    created_at: datetime
    status: str
    decision: str | None

    model_config = {"from_attributes": True}


class BalanceResponse(BaseModel):
    upi_id: str
    name: str
    balance: Decimal
    is_frozen: bool

