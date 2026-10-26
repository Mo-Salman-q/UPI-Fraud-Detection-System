"""
api/services/decision_engine.py
---------------------------------
Converts a model score + optional rule result into a final Decision.

Primary entry point:
    decide(score: float, rule_result: RuleResult | None, cfg: dict) -> Decision

Decision logic (DESIGN.md §2.5):
    score = model(features)
    if rule matches:        decision = rule.action          # rule override
    elif score >= T_hold:   HOLD                            # default 0.70
    elif score >= T_step:   STEP_UP                         # default 0.30
    else:                   ALLOW

Thresholds (DESIGN.md §2.5, §2.1):
    T_hold and T_step are read from the `config` table (key="thresholds").
    Defaults (0.70 / 0.30) are used if the config row is absent.
    Every admin change to thresholds is recorded in audit_log.

Returns:
    Decision enum with values: ALLOW, STEP_UP, HOLD.
    Also returns the risk_band string ("low" | "medium" | "high") used in
    the customer-facing response — this carries no raw score.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from api.models.config import Config

if TYPE_CHECKING:
    from api.services.rules_engine import RuleResult

# ── Defaults ──────────────────────────────────────────────────────────────────
_DEFAULT_T_HOLD = 0.70
_DEFAULT_T_STEP = 0.30


@dataclass(frozen=True)
class Decision:
    action: str       # "ALLOW" | "STEP_UP" | "HOLD"
    risk_band: str    # "low" | "medium" | "high" (coarse; never the raw score)
    rule_name: str | None = None  # set if a rule overrode the model


def _load_thresholds(db: Session) -> tuple[float, float]:
    """
    Return (T_hold, T_step) from the config table, or defaults if absent.
    """
    row: Config | None = db.get(Config, "thresholds")
    if row and isinstance(row.value_json, dict):
        t_hold = float(row.value_json.get("T_hold", _DEFAULT_T_HOLD))
        t_step = float(row.value_json.get("T_step", _DEFAULT_T_STEP))
        return t_hold, t_step
    return _DEFAULT_T_HOLD, _DEFAULT_T_STEP


def _score_to_band(score: float, t_hold: float, t_step: float) -> str:
    """Convert a raw probability to a coarse risk band label."""
    if score >= t_hold:
        return "high"
    if score >= t_step:
        return "medium"
    return "low"


def decide(
    score: float,
    rule_result: "RuleResult | None",
    db: Session,
) -> Decision:
    """
    Apply the decision logic from DESIGN.md §2.5 and return a Decision.

    Parameters
    ----------
    score       : Fraud probability from model_service.predict().
    rule_result : Optional RuleResult from rules_engine.evaluate().
                  If not None, its action overrides the score-based decision.
    db          : Active SQLAlchemy session (for reading thresholds from config).
    """
    t_hold, t_step = _load_thresholds(db)
    risk_band = _score_to_band(score, t_hold, t_step)

    if rule_result is not None:
        return Decision(
            action=rule_result.action,
            risk_band=risk_band,
            rule_name=rule_result.rule_name,
        )

    if score >= t_hold:
        action = "HOLD"
    elif score >= t_step:
        action = "STEP_UP"
    else:
        action = "ALLOW"

    return Decision(action=action, risk_band=risk_band)
