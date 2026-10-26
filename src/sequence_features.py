"""
src/sequence_features.py
-------------------------
Computes time-series / sequential features from a sender's transaction history.

All functions operate on PAST transactions only (strictly before current_ts).

Functions:
    time_since_last(sender_history: pd.DataFrame, current_ts: datetime) -> float
        Seconds elapsed since the sender's most recent transaction.
        Returns a large sentinel value (e.g. 1e9) if there is no history.

    amount_trend(sender_history: pd.DataFrame, current_amount: float,
                 window: int = 3) -> float
        Ratio of current_amount to the mean of the last `window` transactions.
        Returns 1.0 if fewer than `window` prior transactions exist.

Feature definitions (DESIGN.md §2.4):
    time_since_last : gap in seconds since the immediately preceding transaction
    amount_trend    : current amount ÷ mean of last 3 amounts
"""
