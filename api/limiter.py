"""
api/limiter.py
--------------
Rate limiting infrastructure for public endpoints using slowapi.
Enforces protection on /auth/login and /v1/payments (DESIGN.md §3.7).
"""

from __future__ import annotations

import os
from slowapi import Limiter
from slowapi.util import get_remote_address

# Rate limiting can be toggled via RATE_LIMIT_ENABLED env var (default: true)
_is_enabled: bool = os.getenv("RATE_LIMIT_ENABLED", "true").lower() in ("true", "1", "yes", "on")

limiter = Limiter(
    key_func=get_remote_address,
    enabled=_is_enabled,
    default_limits=["120/minute"],
    headers_enabled=False,
)
