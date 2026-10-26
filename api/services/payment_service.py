"""
api/services/payment_service.py
--------------------------------
Orchestrates the end-to-end payment processing flow.

Primary entry points:
    create_payment(payload, sender, db) -> PaymentResult
    confirm_payment(txn_id, sender, db) -> PaymentResult

Processing order (DESIGN.md §2.3):
    1. Validate input (receiver exists, amount > 0, sender != receiver).
    2. Check sender's account balance (and is_frozen flag).
    3. Build features using feature_service.build_features() — history only
       before the transaction timestamp.
    4. Predict fraud probability via model_service.predict().
    5. Apply rules via rules_engine.evaluate().
    6. Determine decision via decision_engine.decide().
    7. Persist transaction + alert (if HOLD) in ONE database transaction.
       Ledger (account balance) is updated ONLY for ALLOW decisions.
    8. Write an audit log entry via audit_service.
    9. Return decision, risk_band, and human-readable message to the router.

Atomicity guarantee:
    Steps 7–8 run inside a single SQLAlchemy Session.commit().
    If any step raises, the session is rolled back and no state is written.

Note: risk score and SHAP reasons must NOT be forwarded to the router's
response for customer-facing calls (DESIGN.md §2.7).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from api.models.account import Account
from api.models.alert import Alert
from api.models.device import Device
from api.models.transaction import Transaction
from api.models.user import User
from api.services import audit_service, decision_engine, explain_service, feature_service
from api.services import model_service, rules_engine


@dataclass
class PaymentResult:
    """Customer-safe payment result (no raw score, no SHAP)."""
    txn_id: int
    status: str       # "COMPLETED" | "PENDING_CONFIRM" | "HELD"
    decision: str     # "ALLOW" | "STEP_UP" | "HOLD"
    risk_band: str    # "low" | "medium" | "high"
    message: str


# Human-readable messages — no risk information exposed to customer.
_MESSAGES: dict[str, str] = {
    "ALLOW":   "Payment completed successfully.",
    "STEP_UP": "Please confirm this payment to proceed.",
    "HOLD":    "Your payment is under review. We will notify you shortly.",
}


def _get_receiver(receiver_upi: str, db: Session) -> User:
    user: User | None = db.query(User).filter(User.upi_id == receiver_upi).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Receiver UPI ID '{receiver_upi}' not found.",
        )
    return user


def _get_account(user_id: int, db: Session) -> Account:
    account: Account | None = db.query(Account).filter(Account.user_id == user_id).first()
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sender account not found.",
        )
    return account


def _upsert_device(user: User, device_fingerprint: str, db: Session) -> Device | None:
    """
    Return existing Device row or create a new one.  Updates last_seen.
    Returns None if device_fingerprint is empty.
    """
    if not device_fingerprint:
        return None

    now = datetime.utcnow()
    device: Device | None = (
        db.query(Device)
        .filter(
            Device.user_id == user.id,
            Device.device_fingerprint == device_fingerprint,
        )
        .first()
    )
    if device is None:
        device = Device(
            user_id=user.id,
            device_fingerprint=device_fingerprint,
            first_seen=now,
            last_seen=now,
        )
        db.add(device)
        db.flush()  # get id before commit
    else:
        device.last_seen = now
    return device


def create_payment(
    receiver_upi: str,
    amount_decimal,
    device_fingerprint: str,
    ip: str,
    city: str,
    sender: User,
    db: Session,
    is_synthetic: bool = False,
) -> PaymentResult:
    """
    Execute the full ALLOW / STEP_UP / HOLD payment flow.

    Parameters
    ----------
    receiver_upi        : UPI ID of the payee.
    amount_decimal      : Decimal amount in INR.
    device_fingerprint  : Client device identifier string.
    ip                  : Client IP address string.
    city                : City name from the client.
    sender              : Authenticated User ORM object.
    db                  : SQLAlchemy session.
    is_synthetic        : True for demo-simulator-generated transactions.
    """
    from decimal import Decimal

    amount = Decimal(str(amount_decimal))

    # ── 1. Validate input ────────────────────────────────────────────────────
    if amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Amount must be greater than zero.",
        )

    receiver = _get_receiver(receiver_upi, db)

    if receiver.id == sender.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sender and receiver cannot be the same account.",
        )

    # ── 2. Balance / frozen check ────────────────────────────────────────────
    sender_account = _get_account(sender.id, db)

    if sender_account.is_frozen:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is frozen. Contact support.",
        )

    if sender_account.balance < amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient balance. Available: ₹{sender_account.balance:.2f}",
        )

    # ── Upsert device (before feature building) ──────────────────────────────
    device = _upsert_device(sender, device_fingerprint, db)

    # ── 3. Build features ────────────────────────────────────────────────────
    txn_time = datetime.utcnow()
    features = feature_service.build_features(
        sender=sender,
        receiver=receiver,
        amount=amount,
        device_fingerprint=device_fingerprint,
        ip=ip,
        city=city,
        txn_time=txn_time,
        db=db,
    )

    # ── 4. Model prediction ──────────────────────────────────────────────────
    try:
        risk_score: float = model_service.predict(features)
    except model_service.ModelNotLoadedError:
        # Graceful degradation: no model → treat as ALLOW (demo safety net).
        risk_score = 0.0

    # ── 5. Rules engine ──────────────────────────────────────────────────────
    rule_result = rules_engine.evaluate(features, db)

    # ── 6. Decision ──────────────────────────────────────────────────────────
    dec = decision_engine.decide(risk_score, rule_result, db)

    # ── 7. Persist (one atomic transaction) ──────────────────────────────────
    txn_status_map = {
        "ALLOW":   "COMPLETED",
        "STEP_UP": "PENDING_CONFIRM",
        "HOLD":    "HELD",
    }
    txn_status = txn_status_map[dec.action]

    txn = Transaction(
        sender_id=sender.id,
        receiver_id=receiver.id,
        amount=amount,
        device_id=device.id if device else None,
        ip=ip,
        city=city,
        created_at=txn_time,
        status=txn_status,
        risk_score=risk_score,
        decision=dec.action,
        model_version=model_service.model_version(),
        features_json=features,
        is_synthetic=is_synthetic,
    )
    db.add(txn)
    db.flush()  # assign txn.id

    # Update ledger ONLY for ALLOW.
    if dec.action == "ALLOW":
        sender_account.balance -= amount

    # Create alert for HOLD decisions.
    if dec.action == "HOLD":
        reasons = explain_service.top_reasons(features, k=3)
        alert = Alert(
            txn_id=txn.id,
            status="OPEN",
            reasons_json=reasons,
        )
        db.add(alert)

    # ── 8. Audit log ─────────────────────────────────────────────────────────
    audit_service.log_action(
        db=db,
        actor_id=sender.id,
        action="PAYMENT_CREATED",
        target=f"transaction:{txn.id}",
        after={
            "decision": dec.action,
            "risk_band": dec.risk_band,
            "rule": dec.rule_name,
            "amount": str(amount),
            "receiver_upi": receiver_upi,
        },
    )

    db.commit()
    db.refresh(txn)

    return PaymentResult(
        txn_id=txn.id,
        status=txn_status,
        decision=dec.action,
        risk_band=dec.risk_band,
        message=_MESSAGES[dec.action],
    )


def confirm_payment(txn_id: int, sender: User, db: Session) -> PaymentResult:
    """
    Complete a STEP_UP transaction after the user confirms.

    Status transitions: PENDING_CONFIRM → COMPLETED.
    Ledger is updated on confirmation.
    """
    txn: Transaction | None = db.get(Transaction, txn_id)
    if txn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found.")

    if txn.sender_id != sender.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your transaction.")

    if txn.status != "PENDING_CONFIRM":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot confirm a transaction with status '{txn.status}'.",
        )

    # Deduct balance.
    sender_account = _get_account(sender.id, db)
    if sender_account.balance < txn.amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient balance at confirmation time. Available: ₹{sender_account.balance:.2f}",
        )

    txn.status = "COMPLETED"
    sender_account.balance -= txn.amount

    audit_service.log_action(
        db=db,
        actor_id=sender.id,
        action="PAYMENT_CONFIRMED",
        target=f"transaction:{txn.id}",
        after={"status": "COMPLETED", "amount": str(txn.amount)},
    )

    db.commit()
    db.refresh(txn)

    return PaymentResult(
        txn_id=txn.id,
        status="COMPLETED",
        decision=txn.decision or "STEP_UP",
        risk_band="medium",  # was step-up risk band
        message="Payment confirmed and completed successfully.",
    )
