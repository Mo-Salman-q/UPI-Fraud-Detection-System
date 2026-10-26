"""
api/routers/admin.py
--------------------
Admin / analyst endpoints.  All routes require at least role="analyst".
Routes that modify config or rules require role="admin".
Every mutating action writes an entry to audit_log via audit_service.

Endpoints (DESIGN.md §2.2):
    GET  /admin/alerts?status=          analyst, admin  — Alert queue
    POST /admin/alerts/{id}/resolve     analyst, admin  — Approve / confirm fraud / escalate
    GET  /admin/transactions            analyst, admin  — Search and filter
    GET  /admin/graph/{upi_id}          analyst, admin  — Account neighbourhood graph
    GET  /admin/config                  admin           — Current thresholds + feature toggles
    PUT  /admin/config                  admin           — Update thresholds/toggles (audited)
    GET  /admin/rules                   admin           — List rules
    POST /admin/rules                   admin           — Create rule
    PUT  /admin/rules/{id}              admin           — Update rule
    GET  /admin/metrics                 analyst, admin  — Alerts per day, review outcomes
    GET  /admin/drift                   admin           — Serves reports/drift.html
    GET  /admin/audit                   admin           — Audit log

UPI IDs are masked in analyst views by default (DESIGN.md §2.7).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.deps import get_current_user, get_db, require_role
from api.models.alert import Alert
from api.models.audit_log import AuditLog
from api.models.config import Config
from api.models.rule import Rule
from api.models.transaction import Transaction
from api.models.user import User
from api.schemas.admin import (
    AdminTransactionOut,
    AlertResponse,
    AuditLogEntry,
    ConfigResponse,
    ConfigUpdateRequest,
    GraphResponse,
    MetricsResponse,
    ResolveRequest,
    ResolveResponse,
    RuleIn,
    RuleOut,
)
from api.services import audit_service, graph_service

router = APIRouter(prefix="/admin", tags=["admin"])

# ── Helpers ───────────────────────────────────────────────────────────────────

_DEFAULT_THRESHOLDS = {"T_hold": 0.70, "T_step": 0.30}
_DEFAULT_TOGGLES = {"use_network_features": True, "use_device_features": True}


def _mask_upi(upi_id: str) -> str:
    """Partially mask a UPI ID for analyst views: 'alice@sentinel' → 'ali**@sentinel'."""
    if "@" not in upi_id:
        return upi_id[:3] + "****" if len(upi_id) > 3 else "****"
    local, domain = upi_id.split("@", 1)
    masked_local = local[:3] + "**" if len(local) > 3 else local[:1] + "**"
    return f"{masked_local}@{domain}"


def _alert_to_response(alert: Alert, db: Session) -> AlertResponse:
    txn: Transaction | None = db.get(Transaction, alert.txn_id)
    sender_upi = ""
    receiver_upi = ""
    if txn:
        s = db.get(User, txn.sender_id)
        r = db.get(User, txn.receiver_id)
        sender_upi = _mask_upi(s.upi_id) if s else ""
        receiver_upi = _mask_upi(r.upi_id) if r else ""

    return AlertResponse(
        id=alert.id,
        txn_id=alert.txn_id,
        status=alert.status,
        reasons=alert.reasons_json or [],
        risk_score=txn.risk_score if txn else None,
        reviewed_at=alert.reviewed_at,
        notes=alert.notes,
        amount=txn.amount if txn else None,
        masked_sender_upi=sender_upi,
        masked_receiver_upi=receiver_upi,
        decision=txn.decision if txn else None,
        created_at=txn.created_at if txn else None,
    )


# ── Alert endpoints ───────────────────────────────────────────────────────────

@router.get(
    "/alerts",
    response_model=list[AlertResponse],
    summary="List alerts (optionally filter by status)",
    dependencies=[Depends(require_role("analyst", "admin"))],
)
def list_alerts(
    status: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list[AlertResponse]:
    q = db.query(Alert)
    if status:
        q = q.filter(Alert.status == status.upper())
    alerts = q.order_by(Alert.id.desc()).limit(limit).all()
    return [_alert_to_response(a, db) for a in alerts]


@router.post(
    "/alerts/{alert_id}/resolve",
    response_model=ResolveResponse,
    summary="Resolve an alert (approve / confirm fraud / escalate)",
)
def resolve_alert(
    alert_id: int,
    body: ResolveRequest,
    reviewer: User = Depends(require_role("analyst", "admin")),
    db: Session = Depends(get_db),
) -> ResolveResponse:
    alert: Alert | None = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found.")
    if alert.status != "OPEN":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Alert is already resolved (status={alert.status}).",
        )

    before = {"status": alert.status}
    alert.status = body.action
    alert.reviewer_id = reviewer.id
    alert.reviewed_at = datetime.utcnow()
    alert.notes = body.notes

    # ── Update Ledger upon APPROVAL ───────────────────────────────────────────
    if body.action == "APPROVED":
        from api.models.account import Account
        txn: Transaction | None = db.get(Transaction, alert.txn_id)
        if txn and txn.status == "HELD":
            sender_acc = db.query(Account).filter(Account.user_id == txn.sender_id).first()
            if sender_acc:
                if sender_acc.balance < txn.amount:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Cannot approve: sender has insufficient balance (₹{sender_acc.balance:.2f}).",
                    )
                sender_acc.balance -= txn.amount
            receiver_acc = db.query(Account).filter(Account.user_id == txn.receiver_id).first()
            if receiver_acc:
                receiver_acc.balance += txn.amount
            txn.status = "COMPLETED"

    audit_service.log_action(
        db=db,
        actor_id=reviewer.id,
        action="ALERT_RESOLVED",
        target=f"alert:{alert_id}",
        before=before,
        after={"status": body.action, "notes": body.notes},
    )
    db.commit()
    return ResolveResponse(
        alert_id=alert_id,
        status=body.action,
        message=f"Alert {alert_id} resolved as {body.action}.",
    )



# ── Transaction search ────────────────────────────────────────────────────────

@router.get(
    "/transactions",
    response_model=list[AdminTransactionOut],
    summary="Search and filter transactions",
    dependencies=[Depends(require_role("analyst", "admin"))],
)
def list_transactions(
    status: str | None = None,
    decision: str | None = None,
    is_synthetic: bool | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list[AdminTransactionOut]:
    q = db.query(Transaction)
    if status:
        q = q.filter(Transaction.status == status.upper())
    if decision:
        q = q.filter(Transaction.decision == decision.upper())
    if is_synthetic is not None:
        q = q.filter(Transaction.is_synthetic == is_synthetic)

    txns = q.order_by(Transaction.created_at.desc()).limit(limit).all()
    result = []
    for t in txns:
        s = db.get(User, t.sender_id)
        r = db.get(User, t.receiver_id)
        result.append(
            AdminTransactionOut(
                id=t.id,
                amount=t.amount,
                masked_sender_upi=_mask_upi(s.upi_id) if s else "",
                masked_receiver_upi=_mask_upi(r.upi_id) if r else "",
                city=t.city,
                ip=t.ip,
                created_at=t.created_at,
                status=t.status,
                decision=t.decision,
                risk_score=t.risk_score,
                is_synthetic=t.is_synthetic,
            )
        )
    return result


# ── Graph ─────────────────────────────────────────────────────────────────────

@router.get(
    "/graph/{upi_id}",
    response_model=GraphResponse,
    summary="Account network neighbourhood graph",
    dependencies=[Depends(require_role("analyst", "admin"))],
)
def get_graph(
    upi_id: str,
    hops: int = 2,
    db: Session = Depends(get_db),
) -> GraphResponse:
    g = graph_service.build_graph(db, until_ts=datetime.utcnow())
    result = graph_service.neighbors(g, upi_id, hops=hops)
    return GraphResponse(nodes=result.nodes, edges=result.edges)


# ── Config ────────────────────────────────────────────────────────────────────

def _get_config_values(db: Session) -> tuple[dict, dict]:
    threshold_row: Config | None = db.get(Config, "thresholds")
    toggle_row: Config | None = db.get(Config, "feature_toggles")
    thresholds = threshold_row.value_json if threshold_row else _DEFAULT_THRESHOLDS.copy()
    toggles = toggle_row.value_json if toggle_row else _DEFAULT_TOGGLES.copy()
    return thresholds, toggles


@router.get(
    "/config",
    response_model=ConfigResponse,
    summary="Get current thresholds and feature toggles",
    dependencies=[Depends(require_role("admin"))],
)
def get_config(db: Session = Depends(get_db)) -> ConfigResponse:
    thresholds, toggles = _get_config_values(db)
    return ConfigResponse(thresholds=thresholds, feature_toggles=toggles)


@router.put(
    "/config",
    response_model=ConfigResponse,
    summary="Update thresholds and/or feature toggles (admin-only; audited)",
)
def update_config(
    body: ConfigUpdateRequest,
    admin: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> ConfigResponse:
    thresholds, toggles = _get_config_values(db)
    before = {"thresholds": thresholds, "feature_toggles": toggles}

    if body.thresholds is not None:
        thresholds.update(body.thresholds)
        row = db.get(Config, "thresholds")
        if row:
            row.value_json = thresholds
            row.updated_by = admin.id
        else:
            db.add(Config(key="thresholds", value_json=thresholds, updated_by=admin.id))

    if body.feature_toggles is not None:
        toggles.update(body.feature_toggles)
        row = db.get(Config, "feature_toggles")
        if row:
            row.value_json = toggles
            row.updated_by = admin.id
        else:
            db.add(Config(key="feature_toggles", value_json=toggles, updated_by=admin.id))

    after = {"thresholds": thresholds, "feature_toggles": toggles}
    audit_service.log_action(
        db=db,
        actor_id=admin.id,
        action="CONFIG_UPDATED",
        target="config:thresholds+feature_toggles",
        before=before,
        after=after,
    )
    db.commit()
    return ConfigResponse(thresholds=thresholds, feature_toggles=toggles)


# ── Rules ─────────────────────────────────────────────────────────────────────

@router.get(
    "/rules",
    response_model=list[RuleOut],
    summary="List all rules",
    dependencies=[Depends(require_role("admin"))],
)
def list_rules(db: Session = Depends(get_db)) -> list[RuleOut]:
    return db.query(Rule).order_by(Rule.id.asc()).all()


@router.post(
    "/rules",
    response_model=RuleOut,
    summary="Create a new rule",
    status_code=201,
)
def create_rule(
    body: RuleIn,
    admin: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> Rule:
    rule = Rule(**body.model_dump())
    db.add(rule)
    db.flush()
    audit_service.log_action(
        db=db,
        actor_id=admin.id,
        action="RULE_CREATED",
        target=f"rule:{rule.id}",
        after=body.model_dump(),
    )
    db.commit()
    db.refresh(rule)
    return rule


@router.put(
    "/rules/{rule_id}",
    response_model=RuleOut,
    summary="Update an existing rule",
)
def update_rule(
    rule_id: int,
    body: RuleIn,
    admin: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> Rule:
    rule: Rule | None = db.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found.")
    before = {"name": rule.name, "action": rule.action, "enabled": rule.enabled}
    for k, v in body.model_dump().items():
        setattr(rule, k, v)
    audit_service.log_action(
        db=db,
        actor_id=admin.id,
        action="RULE_UPDATED",
        target=f"rule:{rule_id}",
        before=before,
        after=body.model_dump(),
    )
    db.commit()
    db.refresh(rule)
    return rule


@router.delete(
    "/rules/{rule_id}",
    summary="Delete a rule (admin-only; audited)",
    status_code=204,
)
def delete_rule(
    rule_id: int,
    admin: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    rule: Rule | None = db.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found.")
    before = {"id": rule.id, "name": rule.name, "action": rule.action, "enabled": rule.enabled}
    db.delete(rule)
    audit_service.log_action(
        db=db,
        actor_id=admin.id,
        action="RULE_DELETED",
        target=f"rule:{rule_id}",
        before=before,
    )
    db.commit()
    return None



# ── Metrics ───────────────────────────────────────────────────────────────────

@router.get(
    "/metrics",
    response_model=MetricsResponse,
    summary="Alert queue metrics and review outcome counts",
    dependencies=[Depends(require_role("analyst", "admin"))],
)
def get_metrics(db: Session = Depends(get_db)) -> MetricsResponse:
    # Alerts per day (last 30 days).
    cutoff = datetime.utcnow() - timedelta(days=30)
    daily_rows = (
        db.query(
            func.date(Transaction.created_at).label("day"),
            func.count(Alert.id).label("count"),
        )
        .join(Alert, Alert.txn_id == Transaction.id)
        .filter(Transaction.created_at >= cutoff)
        .group_by(func.date(Transaction.created_at))
        .order_by(func.date(Transaction.created_at))
        .all()
    )
    alerts_per_day = [{"day": str(r.day), "count": r.count} for r in daily_rows]

    # Review outcome counts.
    outcome_rows = (
        db.query(Alert.status, func.count(Alert.id))
        .group_by(Alert.status)
        .all()
    )
    review_outcome_counts = {r[0]: r[1] for r in outcome_rows}

    total_transactions = db.query(func.count(Transaction.id)).scalar() or 0
    total_held = db.query(func.count(Transaction.id)).filter(Transaction.status == "HELD").scalar() or 0

    return MetricsResponse(
        alerts_per_day=alerts_per_day,
        review_outcome_counts=review_outcome_counts,
        total_transactions=total_transactions,
        total_held=total_held,
    )


# ── Drift report ──────────────────────────────────────────────────────────────

@router.get(
    "/drift",
    summary="Serve latest drift report HTML",
    dependencies=[Depends(require_role("admin"))],
)
def get_drift_report() -> FileResponse:
    import os
    path = os.path.join("reports", "drift.html")
    if not os.path.exists(path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Drift report not found. Run src/drift_monitor.py offline to generate it.",
        )
    return FileResponse(path, media_type="text/html")


# ── Audit log ─────────────────────────────────────────────────────────────────

@router.get(
    "/audit",
    response_model=list[AuditLogEntry],
    summary="Audit log (admin-only)",
    dependencies=[Depends(require_role("admin"))],
)
def get_audit_log(limit: int = 200, db: Session = Depends(get_db)) -> list[AuditLogEntry]:
    entries = (
        db.query(AuditLog)
        .order_by(AuditLog.ts.desc())
        .limit(limit)
        .all()
    )
    return entries


# ── Reset Demo Data ───────────────────────────────────────────────────────────

@router.post(
    "/reset-demo",
    summary="Reset demo data: transactions, alerts, balances (admin-only; audited)",
)
def reset_demo_data(
    admin: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> dict:
    """
    Clears transactions and alerts, resets all customer account balances
    to ₹50,000.00, and unfreezes any frozen accounts.
    """
    from decimal import Decimal
    from api.models.account import Account

    # 1. Delete all alerts and transactions
    alerts_deleted = db.query(Alert).delete()
    txns_deleted = db.query(Transaction).delete()

    # 2. Reset account balances to 50,000.00 and unfreeze
    accounts = db.query(Account).all()
    for acc in accounts:
        acc.balance = Decimal("50000.00")
        acc.is_frozen = False

    # 3. Log audit action
    audit_service.log_action(
        db=db,
        actor_id=admin.id,
        action="DEMO_DATA_RESET",
        target="system:database",
        after={
            "alerts_deleted": alerts_deleted,
            "transactions_deleted": txns_deleted,
            "accounts_reset": len(accounts),
            "balance": "50000.00",
        },
    )
    db.commit()

    return {
        "status": "ok",
        "message": f"Demo data reset: {txns_deleted} transactions & {alerts_deleted} alerts cleared. Accounts restored to ₹50,000.00.",
    }

