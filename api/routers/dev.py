"""
api/routers/dev.py
------------------
Developer / demo simulation endpoints.
Only active when environment variable DEMO_MODE=true (DESIGN.md §2.2, §3.7).
All routes require role="admin".

Endpoints:
    POST /dev/simulate/{scenario}
        Supported scenarios (DESIGN.md §4 Prompt 7):
            rapid_burst     — Many transactions from one sender in a short window
            new_device      — Payment from a previously-unseen device fingerprint
            many_to_one     — Multiple senders paying the same suspicious receiver
            split_payments  — Series of sub-threshold payments to evade rules

Implementation notes:
    - Check DEMO_MODE at request time (not only at startup) so it can be
      toggled without a restart.
    - Simulate transactions using synthetic_upi_generator or by directly
      calling payment_service with synthetic payloads.
    - All generated transactions are flagged is_synthetic=True in the DB.
"""

from __future__ import annotations

import os
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.deps import get_db, require_role
from api.models.user import User
from api.services import payment_service

router = APIRouter(prefix="/dev", tags=["dev"])

Scenario = Literal["rapid_burst", "new_device", "many_to_one", "split_payments"]


def _require_demo_mode() -> None:
    if os.getenv("DEMO_MODE", "false").lower() != "true":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo mode is disabled. Set DEMO_MODE=true to enable simulation endpoints.",
        )


@router.post(
    "/simulate/{scenario}",
    summary="Simulate a fraud attack scenario (DEMO_MODE only)",
)
def simulate_scenario(
    scenario: Scenario,
    current_user: User = Depends(require_role("analyst", "admin")),
    db: Session = Depends(get_db),
) -> dict:
    """
    Run a predefined attack scenario by synthesising transactions through the
    payment_service pipeline.  All resulting transactions are marked is_synthetic=True.
    """
    _require_demo_mode()

    # Find demo customer accounts for use as senders/receivers.
    customers = (
        db.query(User)
        .filter(User.role == "customer")
        .order_by(User.id)
        .limit(6)
        .all()
    )
    if len(customers) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Not enough customer accounts found. Run scripts/seed.py first.",
        )

    sender = customers[0]
    receiver = customers[-1]
    results = []

    if scenario == "rapid_burst":
        # 7 rapid transactions from one sender in < 2 minutes.
        for i in range(7):
            try:
                r = payment_service.create_payment(
                    receiver_upi=receiver.upi_id,
                    amount_decimal="500",
                    device_fingerprint="burst-device-001",
                    ip="10.0.0.1",
                    city="Mumbai",
                    sender=sender,
                    db=db,
                    is_synthetic=True,
                )
                results.append({"txn_id": r.txn_id, "decision": r.decision})
            except Exception as e:
                results.append({"error": str(e)})

    elif scenario == "new_device":
        # Single transaction from an unseen device fingerprint.
        try:
            r = payment_service.create_payment(
                receiver_upi=receiver.upi_id,
                amount_decimal="15000",
                device_fingerprint="unknown-device-xyz-9999",
                ip="192.168.99.99",
                city="Chennai",
                sender=sender,
                db=db,
                is_synthetic=True,
            )
            results.append({"txn_id": r.txn_id, "decision": r.decision})
        except Exception as e:
            results.append({"error": str(e)})

    elif scenario == "many_to_one":
        # Multiple distinct senders paying the same receiver.
        for cust in customers[1:5]:
            try:
                r = payment_service.create_payment(
                    receiver_upi=receiver.upi_id,
                    amount_decimal="3000",
                    device_fingerprint=f"device-{cust.id}",
                    ip=f"10.1.1.{cust.id}",
                    city="Delhi",
                    sender=cust,
                    db=db,
                    is_synthetic=True,
                )
                results.append({"txn_id": r.txn_id, "sender": cust.upi_id, "decision": r.decision})
            except Exception as e:
                results.append({"error": str(e)})

    elif scenario == "split_payments":
        # Series of below-threshold payments to same receiver.
        for i in range(5):
            try:
                r = payment_service.create_payment(
                    receiver_upi=receiver.upi_id,
                    amount_decimal="480",  # just below ₹500 threshold
                    device_fingerprint="split-device-001",
                    ip="10.0.0.2",
                    city="Bangalore",
                    sender=sender,
                    db=db,
                    is_synthetic=True,
                )
                results.append({"txn_id": r.txn_id, "decision": r.decision})
            except Exception as e:
                results.append({"error": str(e)})

    return {
        "scenario": scenario,
        "transactions_created": len(results),
        "results": results,
    }
