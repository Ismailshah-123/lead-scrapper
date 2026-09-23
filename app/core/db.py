"""
Database engine and session management.

Free-first default: SQLite, a single file under data/leads.db, zero setup.
Set DATABASE_URL in .env to point at Postgres instead
(e.g. postgresql+psycopg2://user:pass@host/dbname) — every model and query
in this project uses plain SQLAlchemy Core/ORM, so nothing else needs to
change.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import PROJECT_ROOT, get_secrets

_engine = None
_SessionLocal: sessionmaker | None = None


def get_engine():
    global _engine
    if _engine is None:
        url = get_secrets().database_url
        connect_args = {}
        if url.startswith("sqlite"):
            # Needed for SQLite when a session is used across threads (the
            # dashboard/report generation may run in a different thread
            # than discovery).
            connect_args = {"check_same_thread": False}
            # Ensure the parent directory for a sqlite file: URL exists.
            if ":///" in url:
                db_path = url.split(":///", 1)[1]
                if db_path and db_path != ":memory:":
                    Path(db_path).resolve().parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(url, connect_args=connect_args, future=True)
    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, future=True)
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional scope around a series of operations.

    Usage:
        with session_scope() as session:
            session.add(obj)
    Commits on success, rolls back on exception, always closes.
    """
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create all tables that don't already exist. Safe to call repeatedly."""
    from app.models.models import Base  # local import avoids circulars

    Base.metadata.create_all(bind=get_engine())


def reset_engine_cache() -> None:
    """Used by tests that need a fresh engine bound to a temp database."""
    global _engine, _SessionLocal
    _engine = None
    _SessionLocal = None
