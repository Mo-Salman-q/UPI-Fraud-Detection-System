"""
api/main.py
-----------
FastAPI application factory.

Responsibilities:
- Create and configure the FastAPI app instance.
- Register all API routers (auth, payments, admin, dev).
- Add CORS middleware.
- Mount static files for the UPI app (/upi) and Admin console (/admin-ui)
  *after* all API routers so that the catch-all static route does not shadow
  any API path (see DESIGN.md §2.3).
- Expose GET /health for Render liveness checks (DESIGN.md §3.4).
- Load the ML model once at startup via the lifespan context (MODEL_PATH).

Usage (local):
    uvicorn api.main:app --reload --port 8000

Usage (production):
    uvicorn api.main:app --host 0.0.0.0 --port $PORT
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from dotenv import load_dotenv

# Load .env from project root if present
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from api.database import init_db
from api.deps import is_demo_mode
from api.limiter import limiter
from api.routers import auth, payments, admin, dev
from api.services import model_service

logger = logging.getLogger(__name__)


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Startup:
        1. Create DB tables (create_all — idempotent).
        2. Load the ML model from MODEL_PATH.
    Shutdown:
        Nothing to tear down (model is in memory, DB connections pooled).
    """
    # 1. Initialise DB schema
    logger.info("[startup] Initialising database schema …")
    init_db()
    logger.info("[startup] Database schema ready.")

    # 2. Load model
    model_path = os.getenv("MODEL_PATH", "models/sentinel_v1.pkl")
    try:
        model_service.load_model(model_path)
        logger.info("[startup] Model loaded from %s", model_path)
    except RuntimeError as exc:
        # Warn but don't crash — lets the server start even without a model
        # (useful for tests and the very first deploy before training).
        logger.warning("[startup] Model not loaded: %s", exc)

    yield  # server is running

    logger.info("[shutdown] Server shutting down.")


# ── App factory ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Sentinel AI — UPI Fraud Detection",
    description=(
        "**Prototype** — Simulated UPI payment flow with ML-based fraud detection. "
        "No real money or real UPI network involved."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# ── Rate limiting (slowapi) ───────────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# ── CORS ──────────────────────────────────────────────────────────────────────
# Same-origin in production (both front ends served from the same FastAPI
# process). Opened broadly for local development.
_cors_origins = os.getenv("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health check (must be registered before static mounts) ───────────────────

@app.get("/health", tags=["health"], summary="Liveness check")
def health() -> dict:
    """
    Returns HTTP 200 with a JSON body. Used by Render as the healthCheckPath.
    Reports whether the ML model is loaded and if demo mode is enabled.
    """
    return {
        "status": "ok",
        "model_loaded": model_service._bundle is not None,
        "model_version": model_service.model_version(),
        "demo_mode": is_demo_mode(),
    }


# ── API routers ───────────────────────────────────────────────────────────────

app.include_router(auth.router)
app.include_router(payments.router)
app.include_router(admin.router)
app.include_router(dev.router)


# ── Static files & Web UI (MUST be mounted last so they don't shadow API routes) ──

from fastapi.responses import RedirectResponse

_REPO_ROOT = Path(__file__).resolve().parent.parent
_UPI_DIR = _REPO_ROOT / "frontend" / "upi-app"
_ADMIN_DIR = _REPO_ROOT / "frontend" / "admin"

@app.get("/", include_in_schema=False)
def root():
    """Redirect root to the UPI customer application."""
    return RedirectResponse(url="/upi/")

if _UPI_DIR.exists():
    app.mount("/upi", StaticFiles(directory=str(_UPI_DIR), html=True), name="upi-app")

if _ADMIN_DIR.exists():
    app.mount("/admin-ui", StaticFiles(directory=str(_ADMIN_DIR), html=True), name="admin-ui")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run("api.main:app", host=host, port=port, reload=True)

