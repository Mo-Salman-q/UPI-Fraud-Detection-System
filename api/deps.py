"""
api/deps.py
-----------
Shared FastAPI dependency functions used across all routers.

Provides:
- get_db()           Yields a SQLAlchemy Session; always closes on teardown.
- get_current_user() Decodes and validates the Bearer JWT; raises 401 if
                     invalid or expired.
- require_role()     Returns a dependency factory that raises 403 when the
                     authenticated user does not hold the required role.
                     Roles (from DESIGN.md §2.1): "customer", "analyst", "admin".

Design note (DESIGN.md §2.7):
    Every admin route must call require_role("analyst") or require_role("admin").
    Customers must never receive raw SHAP values or risk scores.
"""

from __future__ import annotations

import os
from typing import Generator

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from api.database import SessionLocal
from api.models.user import User

# ── Environment & JWT settings ───────────────────────────────────────────────
def get_secret_key() -> str:
    """Return JWT secret key from environment or fallback with warning."""
    return os.getenv("SECRET_KEY", "change-me-to-a-long-random-string-at-least-32-chars")


def is_demo_mode() -> bool:
    """Return True if DEMO_MODE environment variable is enabled."""
    return os.getenv("DEMO_MODE", "false").lower() in ("true", "1", "yes", "on")


SECRET_KEY: str = get_secret_key()
ALGORITHM: str = "HS256"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# ── Database session ──────────────────────────────────────────────────────────

def get_db() -> Generator[Session, None, None]:
    """Yield a SQLAlchemy session and close it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── JWT / authentication ──────────────────────────────────────────────────────

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Decode the Bearer JWT, look up the user, and return the ORM object.
    Raises HTTP 401 if the token is missing, malformed, or expired.
    """
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
        user_id: int | None = payload.get("sub")
        if user_id is None:
            raise credentials_exc
        user_id = int(user_id)
    except (JWTError, ValueError):
        raise credentials_exc

    user: User | None = db.get(User, user_id)
    if user is None:
        raise credentials_exc
    return user


# ── Role-based access control ─────────────────────────────────────────────────

_ROLE_HIERARCHY = {"customer": 0, "analyst": 1, "admin": 2}


def require_role(*roles: str):
    """
    Return a FastAPI dependency that raises 403 unless the current user's role
    is in the allowed set.

    Usage:
        @router.get("/admin/alerts", dependencies=[Depends(require_role("analyst", "admin"))])
    """
    allowed = set(roles)

    def _check(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current_user.role}' is not permitted for this endpoint. "
                       f"Required: {sorted(allowed)}",
            )
        return current_user

    return _check
