"""
api/routers/payments.py
-----------------------
Customer-facing payment endpoints.  Requires role="customer" (via deps).

Endpoints (DESIGN.md §2.2):
    POST /v1/payments
        Body : receiver_upi, amount, device_id, ip, city
        Returns: txn_id, status, decision, risk_band, message
        - Delegates the full ALLOW / STEP_UP / HOLD flow to
          payment_service.create_payment().
        - NEVER returns raw risk score or SHAP values to the caller
          (DESIGN.md §2.7).

    POST /v1/payments/{id}/confirm
        - Completes a STEP_UP transaction after the user confirms.
        - Status transitions: PENDING_CONFIRM → COMPLETED.

    GET /v1/payments/history
        - Returns the authenticated customer's own transactions only.

Rate limiting on POST /v1/payments is applied via slowapi (DESIGN.md §3.7).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from api.deps import get_current_user, get_db, require_role
from api.limiter import limiter
from api.models.account import Account
from api.models.transaction import Transaction
from api.models.user import User
from api.schemas.payment import (
    BalanceResponse,
    ConfirmResponse,
    PaymentRequest,
    PaymentResponse,
    TransactionSummary,
)
from api.services import payment_service

router = APIRouter(prefix="/v1/payments", tags=["payments"])


@router.get(
    "/balance",
    response_model=BalanceResponse,
    summary="Get authenticated customer's account balance",
)
def get_balance(
    current_user: User = Depends(require_role("customer", "admin")),
    db: Session = Depends(get_db),
) -> BalanceResponse:
    account: Account | None = db.query(Account).filter(Account.user_id == current_user.id).first()
    return BalanceResponse(
        upi_id=current_user.upi_id,
        name=current_user.name,
        balance=account.balance if account else Decimal("0.00"),
        is_frozen=account.is_frozen if account else False,
    )


@router.post(
    "",
    response_model=PaymentResponse,
    summary="Initiate a UPI payment",
)
@limiter.limit("30/minute")
def create_payment(
    request: Request,
    body: PaymentRequest,
    sender: User = Depends(require_role("customer", "admin")),
    db: Session = Depends(get_db),
) -> PaymentResponse:
    """
    Initiate a payment.  Returns ALLOW/STEP_UP/HOLD decision with a
    user-friendly message.  Raw risk score is never included.
    """
    result = payment_service.create_payment(
        receiver_upi=body.receiver_upi,
        amount_decimal=body.amount,
        device_fingerprint=body.device_id,
        ip=body.ip,
        city=body.city,
        sender=sender,
        db=db,
    )
    return PaymentResponse(
        txn_id=result.txn_id,
        status=result.status,
        decision=result.decision,
        risk_band=result.risk_band,
        message=result.message,
    )


@router.post(
    "/{txn_id}/confirm",

    response_model=ConfirmResponse,
    summary="Confirm a STEP_UP payment",
)
def confirm_payment(
    txn_id: int,
    sender: User = Depends(require_role("customer", "admin")),
    db: Session = Depends(get_db),
) -> ConfirmResponse:
    """
    Complete a payment that is awaiting step-up confirmation.
    Transitions the transaction from PENDING_CONFIRM → COMPLETED.
    """
    result = payment_service.confirm_payment(txn_id=txn_id, sender=sender, db=db)
    return ConfirmResponse(
        txn_id=result.txn_id,
        status=result.status,
        decision=result.decision,
        risk_band=result.risk_band,
        message=result.message,
    )


@router.get(
    "/history",
    response_model=list[TransactionSummary],
    summary="Get own transaction history",
)
def get_history(
    limit: int = 50,
    current_user: User = Depends(require_role("customer", "admin")),
    db: Session = Depends(get_db),
) -> list[TransactionSummary]:
    """
    Return the authenticated user's own transactions (most recent first).
    Only the sender's own transactions are returned — no cross-account leakage.
    """
    txns: list[Transaction] = (
        db.query(Transaction)
        .filter(Transaction.sender_id == current_user.id)
        .order_by(Transaction.created_at.desc())
        .limit(min(limit, 200))
        .all()
    )

    result = []
    for t in txns:
        # Resolve receiver UPI ID.
        receiver_user: User | None = db.get(User, t.receiver_id)
        result.append(
            TransactionSummary(
                id=t.id,
                amount=t.amount,
                receiver_upi=receiver_user.upi_id if receiver_user else "unknown",
                city=t.city,
                created_at=t.created_at,
                status=t.status,
                decision=t.decision,
            )
        )
    return result
