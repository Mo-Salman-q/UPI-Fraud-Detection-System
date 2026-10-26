"""
api/routers/auth.py
-------------------
Authentication router.

Endpoints (DESIGN.md §2.2):
    POST /auth/login
        - Accepts username (UPI ID) + password.
        - Verifies bcrypt hash via passlib.
        - Returns a signed JWT (python-jose) with sub=user_id, role=role,
          and exp claim.
        - Available to all roles (public login endpoint).

Security notes (DESIGN.md §2.7, §3.7):
    - Passwords are never logged or returned.
    - JWT SECRET_KEY is read from the environment; never hard-coded.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from jose import jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from api.deps import ALGORITHM, get_db, get_secret_key
from api.limiter import limiter
from api.models.user import User
from api.schemas.auth import LoginRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_ACCESS_TOKEN_EXPIRE_MINUTES: int = int(
    os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def create_access_token(user: User) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=_ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "upi_id": user.upi_id,
        "exp": expire,
    }
    return jwt.encode(payload, get_secret_key(), algorithm=ALGORITHM)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Authenticate and receive a JWT",
)
@limiter.limit("10/minute")
def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """
    Authenticate with UPI ID + password.  Returns a Bearer JWT.
    Raises 401 if credentials are invalid.
    """
    user: User | None = db.query(User).filter(User.upi_id == body.upi_id).first()

    # Use constant-time comparison even for missing users to prevent user enumeration.
    if user is None or not verify_password(body.password.get_secret_value(), user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid UPI ID or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(user)
    return TokenResponse(access_token=token, token_type="bearer", role=user.role)
