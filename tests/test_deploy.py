"""Settings and plumbing for running on a host such as Vercel."""

import runpy
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from tasktracker.config import Settings, local_timezone
from tasktracker.db import Base, make_engine, normalize_url
from tasktracker.models import now
from tasktracker.schemas import TimeBlockCreate

ENV = ["TASKTRACKER_DATABASE_URL", "DATABASE_URL", "VERCEL", "TASKTRACKER_SECURE_COOKIES"]


@pytest.fixture
def env(monkeypatch):
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture
def timezone(monkeypatch):
    def _set(name):
        monkeypatch.setenv("TASKTRACKER_TIMEZONE", name)
        local_timezone.cache_clear()

    yield _set
    local_timezone.cache_clear()


def test_database_url_comes_from_the_environment(env):
    assert Settings.from_env().database_url.startswith("sqlite:///")

    env.setenv("DATABASE_URL", "postgres://u:p@db/tasks")  # set by hosted Postgres
    assert Settings.from_env().database_url == "postgres://u:p@db/tasks"

    env.setenv("TASKTRACKER_DATABASE_URL", "sqlite:///other.db")  # ours wins
    assert Settings.from_env().database_url == "sqlite:///other.db"


def test_on_vercel(env):
    env.setenv("VERCEL", "1")
    with pytest.raises(RuntimeError, match="Postgres"):
        Settings.from_env()  # SQLite files don't survive there

    env.setenv("DATABASE_URL", "postgres://u:p@db/tasks")
    assert Settings.from_env().secure_cookies is True  # always HTTPS
    env.setenv("TASKTRACKER_SECURE_COOKIES", "false")
    assert Settings.from_env().secure_cookies is False


def test_secure_cookies_are_off_by_default_elsewhere(env):
    assert Settings.from_env().secure_cookies is False
    env.setenv("TASKTRACKER_SECURE_COOKIES", "true")
    assert Settings.from_env().secure_cookies is True


def test_postgres_urls_use_psycopg():
    for url in ["postgres://u:p@db/tasks", "postgresql://u:p@db/tasks?sslmode=require"]:
        engine = make_engine(url)  # doesn't connect yet
        assert engine.url.drivername == "postgresql+psycopg"
        assert engine.url.database == "tasks"
    assert normalize_url("postgresql+psycopg://u@db/tasks") == "postgresql+psycopg://u@db/tasks"
    assert normalize_url("sqlite:///tasks.db") == "sqlite:///tasks.db"


def test_schema_compiles_for_postgres():
    dialect = postgresql.psycopg.dialect()
    for table in Base.metadata.sorted_tables:
        assert "CREATE TABLE" in str(CreateTable(table).compile(dialect=dialect))


def test_the_clock_uses_the_configured_timezone(timezone):
    timezone("Pacific/Kiritimati")  # UTC+14, so never the same as the machine running this
    expected = datetime.now(ZoneInfo("Pacific/Kiritimati")).replace(tzinfo=None)
    assert abs(now() - expected) < timedelta(seconds=5)

    block = TimeBlockCreate(
        title="Call", starts_at="2026-09-25T09:00:00Z", ends_at="2026-09-25T10:00:00Z"
    )
    assert block.starts_at == datetime(2026, 9, 25, 23, 0)


def test_vercel_entrypoint_serves_the_app(tmp_path, env):
    env.setenv("TASKTRACKER_DATABASE_URL", f"sqlite:///{(tmp_path / 'tasks.db').as_posix()}")
    env.setattr(sys, "path", list(sys.path))  # app.py adds src/ to it

    app = runpy.run_path(str(Path(__file__).parents[1] / "app.py"))["app"]
    try:
        with TestClient(app) as client:
            assert client.get("/login").status_code == 200
            assert client.get("/static/js/login.js").status_code == 200
    finally:
        app.state.engine.dispose()
