"""
tests/test_rbac.py
------------------
Role-Based Access Control tests (DESIGN.md §2.8).

Tests cover:
    - Customer cannot access any /admin/* route → 403
    - Analyst can read /admin/alerts and /admin/transactions → 200
    - Analyst cannot PUT /admin/config → 403
    - Analyst cannot POST /admin/rules → 403
    - Admin can access all admin routes
    - Unauthenticated requests to protected routes → 401
    - GET /health is public → 200
    - POST /auth/login with wrong password → 401
"""

from __future__ import annotations

import pytest


# ── Health is public ──────────────────────────────────────────────────────────

def test_health_public(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "model_loaded" in body


# ── Unauthenticated → 401 ─────────────────────────────────────────────────────

def test_unauthenticated_payments(client):
    resp = client.post("/v1/payments", json={})
    assert resp.status_code == 401


def test_unauthenticated_admin_alerts(client):
    resp = client.get("/admin/alerts")
    assert resp.status_code == 401


def test_unauthenticated_admin_config(client):
    resp = client.get("/admin/config")
    assert resp.status_code == 401


# ── Customer cannot access admin routes ───────────────────────────────────────

def test_customer_forbidden_from_admin_alerts(client, seeded_users, customer_token):
    resp = client.get(
        "/admin/alerts",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert resp.status_code == 403


def test_customer_forbidden_from_admin_transactions(client, seeded_users, customer_token):
    resp = client.get(
        "/admin/transactions",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert resp.status_code == 403


def test_customer_forbidden_from_admin_config(client, seeded_users, customer_token):
    resp = client.get(
        "/admin/config",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert resp.status_code == 403


def test_customer_forbidden_from_admin_rules(client, seeded_users, customer_token):
    resp = client.get(
        "/admin/rules",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert resp.status_code == 403


def test_customer_forbidden_from_audit_log(client, seeded_users, customer_token):
    resp = client.get(
        "/admin/audit",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert resp.status_code == 403


# ── Analyst can read but not write config/rules ───────────────────────────────

def test_analyst_can_list_alerts(client, seeded_users, analyst_token):
    resp = client.get(
        "/admin/alerts",
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_analyst_can_list_transactions(client, seeded_users, analyst_token):
    resp = client.get(
        "/admin/transactions",
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_analyst_forbidden_from_admin_config_get(client, seeded_users, analyst_token):
    """Config endpoints are admin-only."""
    resp = client.get(
        "/admin/config",
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert resp.status_code == 403


def test_analyst_forbidden_from_admin_config_put(client, seeded_users, analyst_token):
    resp = client.put(
        "/admin/config",
        json={"thresholds": {"T_hold": 0.80}},
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert resp.status_code == 403


def test_analyst_forbidden_from_rules(client, seeded_users, analyst_token):
    resp = client.get(
        "/admin/rules",
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert resp.status_code == 403


def test_analyst_forbidden_from_audit(client, seeded_users, analyst_token):
    resp = client.get(
        "/admin/audit",
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert resp.status_code == 403


# ── Admin can access everything ───────────────────────────────────────────────

def test_admin_can_get_config(client, seeded_users, admin_token):
    resp = client.get(
        "/admin/config",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "thresholds" in body
    assert "feature_toggles" in body


def test_admin_can_update_config(client, seeded_users, admin_token):
    resp = client.put(
        "/admin/config",
        json={"thresholds": {"T_hold": 0.75, "T_step": 0.35}},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["thresholds"]["T_hold"] == 0.75


def test_admin_can_list_rules(client, seeded_users, admin_token):
    resp = client.get(
        "/admin/rules",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_admin_can_create_rule(client, seeded_users, admin_token):
    resp = client.post(
        "/admin/rules",
        json={
            "name": "Test rule",
            "condition_json": {"feature": "amount", "op": "gt", "value": 999999},
            "action": "HOLD",
            "enabled": True,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Test rule"
    assert body["action"] == "HOLD"


def test_admin_can_list_alerts(client, seeded_users, admin_token):
    resp = client.get(
        "/admin/alerts",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200


def test_admin_can_view_metrics(client, seeded_users, admin_token):
    resp = client.get(
        "/admin/metrics",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "review_outcome_counts" in body


def test_admin_can_view_audit(client, seeded_users, admin_token):
    resp = client.get(
        "/admin/audit",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── Auth tests ────────────────────────────────────────────────────────────────

def test_login_wrong_password(client, seeded_users):
    resp = client.post(
        "/auth/login",
        json={"upi_id": "test_customer@sentinel", "password": "WrongPassword!"},
    )
    assert resp.status_code == 401


def test_login_unknown_user(client, seeded_users):
    resp = client.post(
        "/auth/login",
        json={"upi_id": "nobody@noexist", "password": "anything"},
    )
    assert resp.status_code == 401


def test_login_success_returns_token(client, seeded_users):
    resp = client.post(
        "/auth/login",
        json={"upi_id": "test_customer@sentinel", "password": "TestPass1234!"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["role"] == "customer"


# ── Dev endpoint blocked without DEMO_MODE ────────────────────────────────────

def test_dev_endpoint_blocked_without_demo_mode(client, seeded_users, admin_token, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    resp = client.post(
        "/dev/simulate/rapid_burst",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 403


# ── Rule deletion & Reset Demo RBAC ──────────────────────────────────────────

def test_admin_can_delete_rule(client, seeded_users, admin_token):
    # First create a rule
    create_resp = client.post(
        "/admin/rules",
        json={
            "name": "Temporary deletion rule",
            "condition_json": {"feature": "amount", "op": "gt", "value": 50000},
            "action": "HOLD",
            "enabled": True,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create_resp.status_code == 201
    rule_id = create_resp.json()["id"]

    # Delete the rule
    del_resp = client.delete(
        f"/admin/rules/{rule_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert del_resp.status_code == 204


def test_analyst_forbidden_from_delete_rule(client, seeded_users, analyst_token):
    resp = client.delete(
        "/admin/rules/1",
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert resp.status_code == 403


def test_customer_forbidden_from_reset_demo(client, seeded_users, customer_token):
    resp = client.post(
        "/admin/reset-demo",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert resp.status_code == 403


def test_analyst_forbidden_from_reset_demo(client, seeded_users, analyst_token):
    resp = client.post(
        "/admin/reset-demo",
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert resp.status_code == 403


def test_admin_can_reset_demo(client, seeded_users, admin_token):
    resp = client.post(
        "/admin/reset-demo",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_admin_can_access_drift_report(client, seeded_users, admin_token):
    resp = client.get(
        "/admin/drift",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


def test_rate_limiting_login(client, seeded_users):
    """Calling /auth/login beyond rate limit returns 429 Too Many Requests."""
    from api.limiter import limiter
    limiter.reset()
    try:
        hit_429 = False
        for _ in range(15):
            resp = client.post(
                "/auth/login",
                json={"upi_id": "test_customer@sentinel", "password": "WrongPassword!"},
            )
            if resp.status_code == 429:
                hit_429 = True
                break
        assert hit_429, "Expected HTTP 429 Too Many Requests after exceeding login rate limit"
    finally:
        limiter.reset()


