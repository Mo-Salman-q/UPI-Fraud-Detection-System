"""
api/services/explain_service.py
---------------------------------
Generates human-readable explanation strings for a fraud decision.

Primary entry point:
    top_reasons(features: dict, k: int = 3) -> list[str]

    Returns the top-k feature contributions as plain English strings
    (e.g., "Amount is 8x higher than usual", "New payee").
    Used only when creating HOLD alerts (stored in alerts.reasons_json).
    NEVER returned directly to customer-facing API responses (DESIGN.md §2.7).

Implementation strategy (DESIGN.md §3.3):
    Uses XGBoost's built-in `pred_contribs`:
        booster = model.get_booster()
        contribs = booster.predict(xgb.DMatrix([feature_row]),
                                   pred_contribs=True)
    This avoids importing the `shap` library in the production server
    process (shap is dev-only in requirements-dev.txt).

    The contribs array has one entry per feature plus the bias term
    (last column). Sort by absolute value, return top-k feature names
    mapped to readable labels.

Analyst-facing only:
    Explanation strings appear in GET /admin/alerts and alert detail views.
"""

from __future__ import annotations

import numpy as np
import xgboost as xgb

from src.fraud_model import FEATURE_COLUMNS

# Human-readable labels for each feature column.
_FEATURE_LABELS: dict[str, str] = {
    "amount":                 "Large transaction amount",
    "hour":                   "Unusual transaction hour",
    "type_CASH_IN":           "Cash-in transaction type",
    "type_CASH_OUT":          "Cash-out transaction type",
    "type_DEBIT":             "Debit transaction type",
    "type_PAYMENT":           "Payment transaction type",
    "type_TRANSFER":          "Transfer transaction type",
    "balance_error_orig":     "Sender balance mismatch (possible account drain)",
    "balance_error_dest":     "Receiver balance mismatch",
    "oldbalanceOrg":          "Sender had a low starting balance",
    "newbalanceOrig":         "Sender's ending balance is zero",
    "oldbalanceDest":         "Receiver's previous balance is suspicious",
    "newbalanceDest":         "Receiver's ending balance is suspicious",
    "log_amount":             "Unusually high log-scaled amount",
    "log1p_oldbalanceOrg":    "Low sender balance (log-scaled)",
    "log1p_newbalanceOrig":   "Zero ending balance (log-scaled)",
    # Extended serving-side features (added by feature_service, mapped here)
    "amt_vs_usual":           "Amount is much higher than sender's usual",
    "is_new_payee":           "Payee has never been paid by this sender before",
    "txn_count_5min":         "Unusually high transaction rate in the last 5 minutes",
    "txn_count_1h":           "Unusually high transaction rate in the last hour",
    "txn_count_24h":          "Unusually high transaction rate in the last 24 hours",
    "small_to_same_payee_1h": "Multiple small payments to same payee (split-payment pattern)",
    "time_since_last":        "Unusually short gap since last transaction",
    "amount_trend":           "Escalating transaction amounts",
    "is_new_device":          "Transaction from an unrecognised device",
    "city_changed":           "Transaction from a different city than usual",
    "ip_new":                 "Transaction from a new IP address",
    "receiver_in_degree":     "Receiver accepts payments from many senders",
    "distinct_senders_24h":   "Receiver had many distinct senders recently",
    "receiver_flagged_neighbors": "Receiver is connected to confirmed-fraud accounts",
}


def top_reasons(features: dict[str, float], k: int = 3) -> list[str]:
    """
    Compute the top-k SHAP-like feature contributions using XGBoost's
    built-in pred_contribs (no shap library required).

    Parameters
    ----------
    features : Feature dict (keys = FEATURE_COLUMNS or a superset).
    k        : Number of reasons to return.

    Returns
    -------
    List of human-readable reason strings (analyst-facing only).
    """
    from api.services.model_service import get_booster  # local import to avoid circular

    try:
        booster = get_booster()
    except Exception:
        # Model not loaded (e.g. test without model file) — return generic reasons.
        return _fallback_reasons(features, k)

    # Build feature row in FEATURE_COLUMNS order; pad missing with 0.
    row = np.array(
        [float(features.get(col, 0.0)) for col in FEATURE_COLUMNS],
        dtype=np.float32,
    ).reshape(1, -1)

    try:
        dmat = xgb.DMatrix(row, feature_names=FEATURE_COLUMNS)
        # contribs shape: (1, n_features + 1) — last column is the bias term.
        contribs = booster.predict(dmat, pred_contribs=True)
        feature_contribs = contribs[0, :-1]  # drop bias

        # Take top-k by absolute contribution magnitude.
        top_indices = np.argsort(np.abs(feature_contribs))[::-1][:k]
        reasons: list[str] = []
        for idx in top_indices:
            col = FEATURE_COLUMNS[idx]
            label = _FEATURE_LABELS.get(col, col.replace("_", " ").capitalize())
            reasons.append(label)
        return reasons
    except Exception:
        return _fallback_reasons(features, k)


def _fallback_reasons(features: dict[str, float], k: int) -> list[str]:
    """Heuristic fallback when booster is unavailable."""
    reasons: list[str] = []
    if features.get("balance_error_orig", 0) > 100:
        reasons.append(_FEATURE_LABELS["balance_error_orig"])
    if features.get("is_new_payee", 0):
        reasons.append(_FEATURE_LABELS["is_new_payee"])
    if features.get("amt_vs_usual", 1) > 3:
        reasons.append(_FEATURE_LABELS["amt_vs_usual"])
    if features.get("is_new_device", 0):
        reasons.append(_FEATURE_LABELS["is_new_device"])
    if features.get("txn_count_5min", 0) > 3:
        reasons.append(_FEATURE_LABELS["txn_count_5min"])
    if features.get("receiver_flagged_neighbors", 0) > 0:
        reasons.append(_FEATURE_LABELS["receiver_flagged_neighbors"])
    # If still empty, add a generic reason.
    if not reasons:
        reasons.append("Risk model flagged this transaction")
    return reasons[:k]
