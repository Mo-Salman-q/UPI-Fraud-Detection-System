"""
src/behavior_features.py
-------------------------
Computes sender behavioural features from transaction history.

All functions operate on a DataFrame of PAST transactions (strictly before
the current transaction's timestamp) to avoid temporal leakage.

Functions:
    amt_vs_usual(sender_history: pd.DataFrame, current_amount: float) -> float
        Returns current_amount / (sender_history["amount"].mean() + 1).
        Returns 1.0 if sender has no history.

    is_new_payee(sender_history: pd.DataFrame, receiver_id: int) -> bool
        Returns True if receiver_id does not appear in sender_history.

    velocity_counts(sender_history: pd.DataFrame, now: datetime)
        -> dict with keys: txn_count_5min, txn_count_1h, txn_count_24h
        Counts rows within each lookback window.

    small_to_same_payee_1h(
        sender_history: pd.DataFrame,
        receiver_id: int,
        threshold: float,
        now: datetime,
    ) -> int
        Count of transactions to receiver_id in the past hour where
        amount < threshold (split-payment detection, DESIGN.md §2.4).

Leakage contract:
    Caller MUST filter sender_history to rows with created_at < txn.created_at
    BEFORE calling any function here.
"""
