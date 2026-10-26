"""
tests/conftest.py
-----------------
Shared pytest fixtures for the Sentinel AI test suite.

Fixtures:
    test_db         — Creates an in-memory SQLite database with all tables,
                      yields a Session, then drops all tables on teardown.
    client          — TestClient(app) with the test_db session injected via
                      FastAPI's dependency override mechanism.
    customer_token  — JWT for a seeded customer user.
    analyst_token   — JWT for a seeded analyst user.
    admin_token     — JWT for a seeded admin user.
    seeded_users    — Dict of {role: User} ORM objects for the test users.
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Set environment variables BEFORE importing app modules so that the app
# doesn't try to read a missing .env or use the wrong SECRET_KEY.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key-32-characters-ok")
os.environ.setdefault("MODEL_PATH", "models/sentinel_v1.pkl")
os.environ.setdefault("ADMIN_SEED_PASSWORD", "TestAdmin1234!")

from api.database import SessionLocal, engine as _default_engine
from api.deps import get_db
from api.main import app
from api.models.base import Base
from api.models.user import User
from api.models.account import Account
from api.models.config import Config
from api.models.rule import Rule
from api.routers.auth import create_access_token, hash_password

from sqlalchemy.pool import StaticPool

# ── In-memory test database ───────────────────────────────────────────────────

_TEST_ENGINE = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_TEST_ENGINE)


@pytest.fixture(scope="function")
def test_db() -> Generator[Session, None, None]:
    """
    Create all tables in an in-memory SQLite DB, yield a session, then drop
    everything for isolation between tests.
    """
    # Import all models to register them with Base.metadata.
    import api.models  # noqa: F401

    Base.metadata.create_all(bind=_TEST_ENGINE)
    db = _TestSessionLocal()

    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=_TEST_ENGINE)


@pytest.fixture(scope="function")
def seeded_users(test_db: Session) -> dict[str, User]:
    """
    Seed a minimal set of users (1 customer, 1 analyst, 1 admin) with accounts
    and the default thresholds config row.  Returns a dict keyed by role.
    """
    users = {}
    for role, upi_id, name in [
        ("customer", "test_customer@sentinel", "Test Customer"),
        ("analyst",  "test_analyst@sentinel",  "Test Analyst"),
        ("admin",    "test_admin@sentinel",     "Test Admin"),
    ]:
        user = User(
            name=name,
            upi_id=upi_id,
            password_hash=hash_password("TestPass1234!"),
            role=role,
        )
        test_db.add(user)
        test_db.flush()
        account = Account(user_id=user.id, balance=Decimal("50000.00"), is_frozen=False)
        test_db.add(account)
        users[role] = user

    # Add a second customer so payments can have distinct sender + receiver.
    receiver = User(
        name="Receiver User",
        upi_id="receiver@sentinel",
        password_hash=hash_password("TestPass1234!"),
        role="customer",
    )
    test_db.add(receiver)
    test_db.flush()
    test_db.add(Account(user_id=receiver.id, balance=Decimal("50000.00"), is_frozen=False))
    users["receiver"] = receiver

    # Default thresholds.
    test_db.add(Config(key="thresholds", value_json={"T_hold": 0.70, "T_step": 0.30}))

    test_db.commit()
    return users


def _make_token(user: User) -> str:
    return create_access_token(user)


@pytest.fixture(scope="function")
def customer_token(seeded_users: dict[str, User]) -> str:
    return _make_token(seeded_users["customer"])


@pytest.fixture(scope="function")
def analyst_token(seeded_users: dict[str, User]) -> str:
    return _make_token(seeded_users["analyst"])


@pytest.fixture(scope="function")
def admin_token(seeded_users: dict[str, User]) -> str:
    return _make_token(seeded_users["admin"])


@pytest.fixture(scope="function")
def client(test_db: Session):
    """
    TestClient with the DB dependency overridden to use the in-memory test DB.
    Model load errors are tolerated so tests can run without a trained model.
    """
    def _override_get_db():
        try:
            yield test_db
        finally:
            pass  # session teardown handled by test_db fixture

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()
