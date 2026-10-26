"""
scripts/seed.py
---------------
Database seed script.  Run once after the DB schema is initialised.

Usage:
    python scripts/seed.py

Environment variables required:
    DATABASE_URL        — SQLite or PostgreSQL connection string
    ADMIN_SEED_PASSWORD — Password for the admin account (DESIGN.md §3.5)

Creates (DESIGN.md §3.6):
    5 demo customers : customer1@sentinel … customer5@sentinel
                       Default password: "Demo1234!" (change for production)
    1 analyst        : analyst1@sentinel
                       Default password: "Analyst1234!"
    1 admin          : admin@sentinel
                       Password read from ADMIN_SEED_PASSWORD env var
    Each user gets one Account with a starting balance of ₹50,000.

Safety:
    Checks for existing rows before inserting; safe to run multiple times
    (idempotent on upi_id).

Audit:
    The admin user creation is recorded in audit_log with actor_id=None
    (system action).
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal
from pathlib import Path

# Make sure the repo root is on the Python path when running as a script.
_repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(_repo_root))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Load .env if present (for local development).
try:
    from dotenv import load_dotenv
    load_dotenv(_repo_root / ".env")
except ImportError:
    pass

from api.database import SessionLocal, init_db
from api.models.account import Account
from api.models.audit_log import AuditLog
from api.models.config import Config
from api.models.rule import Rule
from api.models.user import User
from api.routers.auth import hash_password

# ── Demo user definitions ─────────────────────────────────────────────────────

_ADMIN_PASSWORD: str = os.getenv("ADMIN_SEED_PASSWORD", "")
if not _ADMIN_PASSWORD:
    print(
        "[seed] ERROR: ADMIN_SEED_PASSWORD environment variable is not set.\n"
        "       Set it before running this script:\n"
        "       $Env:ADMIN_SEED_PASSWORD='YourStrongPassword!'\n"
        "       Or add it to your .env file.",
        file=sys.stderr,
    )
    sys.exit(1)

_CUSTOMERS = [
    {"name": f"Customer {i}", "upi_id": f"customer{i}@sentinel", "password": "Demo1234!"}
    for i in range(1, 6)
]
_ANALYST = {"name": "Analyst One", "upi_id": "analyst1@sentinel", "password": "Analyst1234!"}
_ADMIN = {"name": "Admin", "upi_id": "admin@sentinel", "password": _ADMIN_PASSWORD}

# ── Seed rules ────────────────────────────────────────────────────────────────

_DEFAULT_RULES = [
    {
        "name": "New payee over ₹10,000 → STEP_UP",
        "condition_json": {
            "feature": "is_new_payee",
            "op": "eq",
            "value": True,
            "and": {"feature": "amount", "op": "gt", "value": 10000},
        },
        "action": "STEP_UP",
        "enabled": True,
    },
    {
        "name": "Rapid burst (>5 txns in 5 min) → HOLD",
        "condition_json": {"feature": "txn_count_5min", "op": "gt", "value": 5},
        "action": "HOLD",
        "enabled": True,
    },
    {
        "name": "Flagged neighbour receiver → HOLD",
        "condition_json": {"feature": "receiver_flagged_neighbors", "op": "gt", "value": 0},
        "action": "HOLD",
        "enabled": True,
    },
]

# ── Seed config ───────────────────────────────────────────────────────────────

_DEFAULT_CONFIG = {
    "thresholds": {"T_hold": 0.70, "T_step": 0.30},
    "feature_toggles": {"use_network_features": True, "use_device_features": True},
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _upsert_user(
    db,
    name: str,
    upi_id: str,
    password: str,
    role: str,
    audit_actor_id: int | None = None,
) -> User:
    existing: User | None = db.query(User).filter(User.upi_id == upi_id).first()
    if existing:
        print(f"  [skip] {upi_id} already exists (id={existing.id})")
        return existing

    user = User(
        name=name,
        upi_id=upi_id,
        password_hash=hash_password(password),
        role=role,
    )
    db.add(user)
    db.flush()  # assign user.id

    account = Account(user_id=user.id, balance=Decimal("50000.00"), is_frozen=False)
    db.add(account)

    if role == "admin":
        entry = AuditLog(
            actor_id=audit_actor_id,
            action="USER_SEEDED",
            target=f"user:{user.id}",
            after_json={"upi_id": upi_id, "role": role},
        )
        db.add(entry)

    print(f"  [create] {role:8s} {upi_id}")
    return user


def _upsert_rule(db, rule_data: dict) -> None:
    existing = db.query(Rule).filter(Rule.name == rule_data["name"]).first()
    if existing:
        print(f"  [skip] Rule '{rule_data['name']}' already exists")
        return
    db.add(Rule(**rule_data))
    print(f"  [create] Rule '{rule_data['name']}'")


def _upsert_config(db, key: str, value: dict) -> None:
    existing: Config | None = db.get(Config, key)
    if existing:
        print(f"  [skip] Config '{key}' already exists")
        return
    db.add(Config(key=key, value_json=value))
    print(f"  [create] Config '{key}'")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("\n=== Sentinel AI seed script ===\n")

    # Ensure schema exists.
    print("[init] Creating DB tables …")
    init_db()
    print("[init] Done.\n")

    db = SessionLocal()
    try:
        print("[seed] Users & accounts:")
        for c in _CUSTOMERS:
            _upsert_user(db, c["name"], c["upi_id"], c["password"], "customer")

        _upsert_user(db, _ANALYST["name"], _ANALYST["upi_id"], _ANALYST["password"], "analyst")
        _upsert_user(db, _ADMIN["name"], _ADMIN["upi_id"], _ADMIN["password"], "admin")

        print("\n[seed] Rules:")
        for r in _DEFAULT_RULES:
            _upsert_rule(db, r)

        print("\n[seed] Config:")
        for key, value in _DEFAULT_CONFIG.items():
            _upsert_config(db, key, value)

        db.commit()
        print("\n[seed] All changes committed.\n")
        print("Demo users:")
        print("  Customers : customer1@sentinel … customer5@sentinel  (pw: Demo1234!)")
        print("  Analyst   : analyst1@sentinel  (pw: Analyst1234!)")
        print("  Admin     : admin@sentinel      (pw: <ADMIN_SEED_PASSWORD>)")

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
