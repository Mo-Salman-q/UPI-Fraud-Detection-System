"""
api/services/rules_engine.py
-----------------------------
Evaluates business rules against a transaction and its feature vector.
Rules may override the model score and force a specific decision.

Primary entry point:
    evaluate(txn_features: dict, db) -> RuleResult | None

    Returns a RuleResult (action, rule_name, reason) if a matching enabled
    rule fires, or None if no rule applies.

Rule storage (DESIGN.md §2.1):
    Rules are stored in the `rules` table:
        id, name, condition_json, action, enabled
    condition_json describes the predicate in a structured format:
        Single condition:
            {"feature": "is_new_payee", "op": "eq", "value": true}
        AND-chained conditions:
            {"feature": "is_new_payee", "op": "eq", "value": true,
             "and": {"feature": "amount", "op": "gt", "value": 10000}}

Rule evaluation order:
    1. Load enabled rules from DB ordered by id (ascending).
    2. Evaluate each condition against the feature dict.
    3. Return on the first match (rules are ordered by priority / id).

Example rules (DESIGN.md §4 Prompt 6):
    - "New payee AND amount > ₹10,000 → STEP_UP"
    - "txn_count_5min > 5 → HOLD"
    - "receiver_flagged_neighbors > 0 → HOLD"
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from api.models.rule import Rule

# Supported comparison operators
_OPS = {
    "eq":  lambda a, b: a == b,
    "ne":  lambda a, b: a != b,
    "gt":  lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "lt":  lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
}


@dataclass(frozen=True)
class RuleResult:
    action: str          # "ALLOW" | "STEP_UP" | "HOLD"
    rule_name: str       # human-readable rule name for logging
    reason: str          # short explanation string


def _eval_condition(condition: dict[str, Any], features: dict[str, float]) -> bool:
    """
    Recursively evaluate a condition dict against *features*.

    Supports AND chaining via the optional "and" key.
    """
    feature_name: str = condition.get("feature", "")
    op_name: str = condition.get("op", "eq")
    value: Any = condition.get("value")

    feature_value = features.get(feature_name, 0.0)

    op_fn = _OPS.get(op_name)
    if op_fn is None:
        # Unknown operator — skip this condition (safe default).
        return False

    # Coerce booleans: JSON true/false → 1.0/0.0 for numeric comparison
    if isinstance(value, bool):
        value = 1.0 if value else 0.0
    if isinstance(feature_value, bool):
        feature_value = 1.0 if feature_value else 0.0

    result = op_fn(float(feature_value), float(value))

    # AND-chain: both sub-conditions must be true.
    if result and "and" in condition:
        result = result and _eval_condition(condition["and"], features)

    return bool(result)


def evaluate(
    features: dict[str, float],
    db: Session,
) -> RuleResult | None:
    """
    Evaluate all enabled rules in ascending id order.  Return the first
    matching RuleResult, or None if no rule fires.

    Parameters
    ----------
    features : Feature dict from feature_service.build_features().
    db       : Active SQLAlchemy session.
    """
    rules: list[Rule] = (
        db.query(Rule)
        .filter(Rule.enabled.is_(True))
        .order_by(Rule.id.asc())
        .all()
    )

    for rule in rules:
        condition = rule.condition_json
        if not isinstance(condition, dict):
            continue
        if _eval_condition(condition, features):
            return RuleResult(
                action=rule.action,
                rule_name=rule.name,
                reason=f"Rule '{rule.name}' matched",
            )

    return None
