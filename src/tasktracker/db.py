"""Database engine, session factory and declarative base."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


def normalize_url(url: str) -> str:
    """Hosted Postgres hands out ``postgres://`` or ``postgresql://`` URLs; use psycopg 3."""
    for scheme in ("postgres://", "postgresql://"):
        if url.startswith(scheme):
            return "postgresql+psycopg://" + url.removeprefix(scheme)
    return url


def make_engine(url: str) -> Engine:
    url = normalize_url(url)
    kwargs: dict[str, Any] = {}
    is_sqlite = url.startswith("sqlite")
    if is_sqlite:
        # FastAPI runs sync endpoints in a thread pool.
        kwargs["connect_args"] = {"check_same_thread": False}
        database = make_url(url).database
        if database in (None, "", ":memory:"):
            # One shared connection, otherwise every connection gets its own empty DB.
            kwargs["poolclass"] = StaticPool
        else:
            # SQLite creates the file, but not the folder it lives in.
            Path(database).parent.mkdir(parents=True, exist_ok=True)
    else:
        # Serverless hosts freeze between requests; don't hand out connections that died.
        kwargs["pool_pre_ping"] = True
        if url.startswith("postgresql+psycopg"):
            # Connection poolers in transaction mode (Neon, Supabase) lose prepared statements.
            kwargs["connect_args"] = {"prepare_threshold": None}

    engine = create_engine(url, **kwargs)

    if is_sqlite:

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    from tasktracker import models  # noqa: F401  (registers the tables on Base.metadata)

    Base.metadata.create_all(engine)
