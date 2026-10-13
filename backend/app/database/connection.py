"""Database engine / session management.

SQLite is the default for the local prototype; set ``DATABASE_URL`` to a
PostgreSQL URL (``postgresql+psycopg://user:pw@host/db``) for deployment.
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.core.config import PROJECT_ROOT, get_settings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def _normalise_sqlite_url(url: str) -> str:
    """Make relative SQLite paths relative to the project root and create the folder."""
    prefix = "sqlite:///"
    if not url.startswith(prefix) or ":memory:" in url:
        return url
    raw = url[len(prefix):]
    path = Path(raw)
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"{prefix}{path.as_posix()}"


def build_engine(url: str, *, in_memory_shared: bool = False) -> Engine:
    url = _normalise_sqlite_url(url)
    kwargs: dict = {"future": True, "pool_pre_ping": True}
    is_sqlite = url.startswith("sqlite")
    if is_sqlite:
        # background detection threads use their own sessions
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        if in_memory_shared or ":memory:" in url:
            kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)

    if is_sqlite:
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            if ":memory:" not in url:
                cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    return engine


def configure_database(url: str | None = None) -> Engine:
    """(Re)configure the global engine. Tests call this with an in-memory URL."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = build_engine(url or get_settings().database_url)
    _session_factory = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        configure_database()
    assert _engine is not None
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    if _session_factory is None:
        configure_database()
    assert _session_factory is not None
    return _session_factory


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    """Create all tables (idempotent). For schema changes in production, use Alembic."""
    from backend.app import models  # noqa: F401  (registers tables)

    models.Base.metadata.create_all(bind=get_engine())


def check_database() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:  # pragma: no cover - reported via /health
        return False
