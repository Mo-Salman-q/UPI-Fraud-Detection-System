"""
api/database.py
---------------
SQLAlchemy engine and session factory.

DATABASE_URL is read from the environment. For local dev, SQLite is used
(sqlite:///./sentinel.db). For production, a PostgreSQL URL (e.g. Neon) is expected.

Render / Neon note (DESIGN.md §3.5):
    - If DATABASE_URL starts with "postgres://", it is rewritten to
      "postgresql://" for SQLAlchemy 2.x compatibility.
    - PostgreSQL connections require SSL (sslmode=require).
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker


def format_database_url(url: str) -> tuple[str, dict]:
    """
    Format and sanitize database URL for SQLAlchemy and Neon/PostgreSQL.
    - Converts postgres:// to postgresql:// (required by SQLAlchemy 2.x)
    - Enforces SSL (sslmode=require) on PostgreSQL connections (required by Neon)
    - Configures SQLite thread safety when SQLite is used
    """
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    connect_args: dict = {}
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    elif url.startswith("postgresql"):
        if "sslmode=" not in url:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}sslmode=require"
        connect_args = {"sslmode": "require"}

    return url, connect_args


_raw_url: str = os.getenv("DATABASE_URL", "sqlite:///./sentinel.db")
DATABASE_URL, _connect_args = format_database_url(_raw_url)

engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    # Ping connection on checkout to gracefully handle recycled connections
    pool_pre_ping=True,
)

# Enable WAL mode for SQLite — better concurrent read/write performance.
if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Create all tables defined in api.models (called from app lifespan)."""
    # Import models so their metadata is registered before create_all.
    import api.models  # noqa: F401
    from api.models.base import Base
    Base.metadata.create_all(bind=engine)
