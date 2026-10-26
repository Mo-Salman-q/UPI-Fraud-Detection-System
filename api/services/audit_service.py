"""
api/services/audit_service.py
------------------------------
Records immutable audit log entries for every state-changing action.

Primary entry point:
    log_action(
        db,
        actor_id: int | None,
        action: str,
        target: str,
        before: dict | None = None,
        after: dict | None = None,
    ) -> None

    Inserts a row into the `audit_log` table (DESIGN.md §2.1):
        id, actor_id, action, target, before_json, after_json, ts

Actions that MUST be audited (DESIGN.md §2.7, §2.2):
    - Alert resolved (approve / confirm fraud / escalate)
    - Config updated (thresholds, feature toggles)
    - Rule created / updated
    - Admin seed account created

Usage pattern:
    Call log_action() inside the same SQLAlchemy transaction as the
    mutating operation so that audit entries are atomic with the change.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from api.models.audit_log import AuditLog


def log_action(
    db: Session,
    actor_id: int | None,
    action: str,
    target: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditLog:
    """
    Insert an audit log entry.

    Parameters
    ----------
    db        : Active SQLAlchemy session (caller must commit).
    actor_id  : User ID of the person who triggered the action.  Use None (or 0
                mapped to None) for system-initiated actions (e.g. seed script).
    action    : Short action name, e.g. "ALERT_RESOLVED", "CONFIG_UPDATED".
    target    : Human-readable target identifier, e.g. "alert:42".
    before    : Serialisable dict of state before the change (may be None).
    after     : Serialisable dict of state after the change (may be None).

    Returns
    -------
    The newly created AuditLog ORM object (not yet flushed; caller commits).
    """
    entry = AuditLog(
        actor_id=actor_id,
        action=action,
        target=target,
        before_json=before,
        after_json=after,
    )
    db.add(entry)
    return entry
