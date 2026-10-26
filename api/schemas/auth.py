"""
api/schemas/auth.py
-------------------
Pydantic models for authentication request and response payloads.

Models:
    LoginRequest   : upi_id (str), password (str)
    TokenResponse  : access_token (str), token_type="bearer", role (str)

Security note:
    Password fields use SecretStr so the value is not accidentally
    logged or included in repr() output (DESIGN.md §2.7).
"""

from __future__ import annotations

from pydantic import BaseModel, SecretStr


class LoginRequest(BaseModel):
    upi_id: str
    password: SecretStr


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
