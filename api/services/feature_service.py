"""
api/services/feature_service.py
---------------------------------
Builds the feature vector for a pending transaction.

Primary entry point:
    build_features(txn, db) -> dict[str, float | int | bool]

Contract (DESIGN.md §2.4):
    ALL features must use ONLY data strictly before txn.created_at.
    Querying rows with created_at >= txn.created_at is a temporal leak and
    will invalidate the model's offline-to-online consistency guarantee.

Feature groups produced (see DESIGN.md §2.4 for exact definitions):
    Base          : amount, transaction type encoding, hour of day
    Balance       : balance_error_orig (PaySim-style mismatch)
    Behaviour     : amt_vs_usual, is_new_payee
    Velocity      : txn_count_5min, txn_count_1h, txn_count_24h
    Splitting     : small_to_same_payee_1h
    Sequence      : time_since_last, amount_trend
    Device        : is_new_device, city_changed, ip_new
    Network       : receiver_in_degree, distinct_senders_24h
    Cross-account : receiver_flagged_neighbors

Shared feature-column list:
    Import FEATURE_COLUMNS from src.fraud_model so that the serving-time
    feature vector always matches the training-time column order exactly.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.models.alert import Alert
from api.models.device import Device
from api.models.transaction import Transaction
from api.models.user import User
from src.fraud_model import FEATURE_COLUMNS

if TYPE_CHECKING:
    pass

# Split-payment threshold — amounts below this are counted for the splitting feature.
_SPLIT_THRESHOLD = Decimal("500")


def build_features(
    sender: User,
    receiver: User,
    amount: Decimal,
    device_fingerprint: str,
    ip: str,
    city: str,
    txn_time: datetime,
    db: Session,
) -> dict[str, float]:
    """
    Build the full feature dict for a prospective transaction.

    All DB queries use ``created_at < txn_time`` (strict less-than) to
    prevent any temporal leakage from future rows.

    Parameters
    ----------
    sender   : ORM User — the payer.
    receiver : ORM User — the payee.
    amount   : Transaction amount in rupees.
    device_fingerprint : Client-supplied device identifier.
    ip       : Client IP address string.
    city     : City name from the client.
    txn_time : The prospective transaction timestamp (use datetime.utcnow() in
               production; the feature service never calls now() itself so that
               tests can inject a fixed time).
    db       : Active SQLAlchemy session.

    Returns
    -------
    dict mapping FEATURE_COLUMNS names (and extra serving-side names) to floats.
    """
    feats: dict[str, float] = {}

    # ── Base ──────────────────────────────────────────────────────────────────
    feats["amount"] = float(amount)
    feats["hour"] = float(txn_time.hour)
    # Transaction type encoding — for demo UPI payments we treat everything as TRANSFER.
    for t in ["CASH_IN", "CASH_OUT", "DEBIT", "PAYMENT", "TRANSFER"]:
        feats[f"type_{t}"] = 0.0
    feats["type_TRANSFER"] = 1.0

    # ── Balance (PaySim-style) ─────────────────────────────────────────────────
    # In a real bank we'd read balances from the ledger before and after.
    # Here we approximate using the current account balance as oldbalanceOrg.
    from api.models.account import Account  # local to avoid circular at module load

    sender_account: Account | None = (
        db.query(Account).filter(Account.user_id == sender.id).first()
    )
    old_bal_orig = float(sender_account.balance) if sender_account else 0.0
    new_bal_orig = max(0.0, old_bal_orig - float(amount))
    balance_error_orig = old_bal_orig - float(amount) - new_bal_orig

    feats["balance_error_orig"] = balance_error_orig
    feats["balance_error_dest"] = 0.0  # not tracked in demo
    feats["oldbalanceOrg"] = old_bal_orig
    feats["newbalanceOrig"] = new_bal_orig
    feats["oldbalanceDest"] = 0.0
    feats["newbalanceDest"] = 0.0

    # ── Log-scaled amounts ────────────────────────────────────────────────────
    feats["log_amount"] = float(np.log1p(float(amount)))
    feats["log1p_oldbalanceOrg"] = float(np.log1p(old_bal_orig))
    feats["log1p_newbalanceOrig"] = float(np.log1p(new_bal_orig))

    # ── Behaviour ─────────────────────────────────────────────────────────────
    # amt_vs_usual: amount ÷ (sender's past mean + 1)
    past_txns = (
        db.query(Transaction)
        .filter(
            Transaction.sender_id == sender.id,
            Transaction.created_at < txn_time,
            Transaction.status.in_(["COMPLETED", "PENDING_CONFIRM"]),
        )
        .all()
    )
    if past_txns:
        past_mean = float(np.mean([float(t.amount) for t in past_txns]))
        feats["amt_vs_usual"] = float(amount) / (past_mean + 1.0)
    else:
        feats["amt_vs_usual"] = 1.0  # no history → treat as normal

    # is_new_payee: sender has never paid this receiver before
    paid_before = any(t.receiver_id == receiver.id for t in past_txns)
    feats["is_new_payee"] = 0.0 if paid_before else 1.0

    # ── Velocity ──────────────────────────────────────────────────────────────
    def _count_sender_txns(window_minutes: int) -> int:
        cutoff = txn_time - timedelta(minutes=window_minutes)
        return sum(1 for t in past_txns if t.created_at >= cutoff)

    feats["txn_count_5min"] = float(_count_sender_txns(5))
    feats["txn_count_1h"] = float(_count_sender_txns(60))
    feats["txn_count_24h"] = float(_count_sender_txns(1440))

    # ── Splitting ─────────────────────────────────────────────────────────────
    # Count of under-threshold transactions to same receiver in last hour.
    cutoff_1h = txn_time - timedelta(hours=1)
    feats["small_to_same_payee_1h"] = float(
        sum(
            1
            for t in past_txns
            if t.receiver_id == receiver.id
            and t.created_at >= cutoff_1h
            and t.amount < _SPLIT_THRESHOLD
        )
    )

    # ── Sequence ──────────────────────────────────────────────────────────────
    recent = sorted(past_txns, key=lambda t: t.created_at, reverse=True)
    if recent:
        last_txn = recent[0]
        gap_seconds = (txn_time - last_txn.created_at).total_seconds()
        feats["time_since_last"] = float(gap_seconds)
        # amount_trend: ratio of current amount vs mean of last 3 amounts
        last3_amounts = [float(t.amount) for t in recent[:3]]
        mean_last3 = float(np.mean(last3_amounts)) if last3_amounts else 1.0
        feats["amount_trend"] = float(amount) / (mean_last3 + 1.0)
    else:
        feats["time_since_last"] = 86400.0  # 24 h — "long time since last"
        feats["amount_trend"] = 1.0

    # ── Device ────────────────────────────────────────────────────────────────
    # is_new_device: device_fingerprint never seen for this user before txn_time
    known_devices = (
        db.query(Device)
        .filter(
            Device.user_id == sender.id,
            Device.first_seen < txn_time,
        )
        .all()
    )
    known_fps = {d.device_fingerprint for d in known_devices}
    feats["is_new_device"] = 0.0 if device_fingerprint in known_fps else 1.0

    # city_changed: sender's last transaction was from a different city
    if recent:
        last_city = recent[0].city or ""
        feats["city_changed"] = 0.0 if (city == last_city) else 1.0
    else:
        feats["city_changed"] = 0.0

    # ip_new: IP not seen in sender's transaction history
    seen_ips = {t.ip for t in past_txns if t.ip}
    feats["ip_new"] = 0.0 if ip in seen_ips else 1.0

    # ── Network ───────────────────────────────────────────────────────────────
    # receiver_in_degree: how many distinct senders have paid receiver before txn_time
    in_degree = (
        db.query(func.count(func.distinct(Transaction.sender_id)))
        .filter(
            Transaction.receiver_id == receiver.id,
            Transaction.created_at < txn_time,
        )
        .scalar()
        or 0
    )
    feats["receiver_in_degree"] = float(in_degree)

    # distinct_senders_24h: distinct senders to receiver in the past 24 h
    cutoff_24h = txn_time - timedelta(hours=24)
    distinct_24h = (
        db.query(func.count(func.distinct(Transaction.sender_id)))
        .filter(
            Transaction.receiver_id == receiver.id,
            Transaction.created_at >= cutoff_24h,
            Transaction.created_at < txn_time,
        )
        .scalar()
        or 0
    )
    feats["distinct_senders_24h"] = float(distinct_24h)

    # ── Cross-account ─────────────────────────────────────────────────────────
    # receiver_flagged_neighbors: count of receiver's counterparties with
    # a CONFIRMED_FRAUD alert before txn_time.
    # We find all users that transacted with receiver, then check their alerts.
    flagged = (
        db.query(func.count(func.distinct(Transaction.sender_id)))
        .join(Alert, Alert.txn_id == Transaction.id)
        .filter(
            Transaction.receiver_id == receiver.id,
            Transaction.created_at < txn_time,
            Alert.status == "CONFIRMED_FRAUD",
        )
        .scalar()
        or 0
    )
    feats["receiver_flagged_neighbors"] = float(flagged)

    return feats
