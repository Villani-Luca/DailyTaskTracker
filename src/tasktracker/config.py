"""Runtime settings, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import make_url

DEFAULT_DB_PATH = Path.home() / ".dailytasktracker" / "tasks.db"


@dataclass(frozen=True)
class Settings:
    database_url: str
    host: str = "127.0.0.1"
    port: int = 8000
    # Send the login cookie over HTTPS only. Turn on whenever the app is served over HTTPS.
    secure_cookies: bool = False

    @property
    def safe_database_url(self) -> str:
        """The database URL with its password masked, for printing."""
        url = make_url(self.database_url)
        return self.database_url if url.password is None else url.render_as_string()

    @classmethod
    def from_env(cls) -> Settings:
        on_vercel = bool(os.environ.get("VERCEL"))
        # DATABASE_URL is what hosted Postgres integrations (Neon on Vercel, ...) set.
        database_url = os.environ.get("TASKTRACKER_DATABASE_URL") or os.environ.get("DATABASE_URL")
        if not database_url:
            if on_vercel:
                raise RuntimeError(
                    "Set DATABASE_URL (or TASKTRACKER_DATABASE_URL) to a Postgres database: "
                    "files written on Vercel don't last, so SQLite won't work there."
                )
            database_url = f"sqlite:///{DEFAULT_DB_PATH.as_posix()}"

        secure_cookies = os.environ.get("TASKTRACKER_SECURE_COOKIES")
        return cls(
            database_url=database_url,
            host=os.environ.get("TASKTRACKER_HOST", "127.0.0.1"),
            port=int(os.environ.get("TASKTRACKER_PORT", "8000")),
            # Vercel always serves over HTTPS.
            secure_cookies=on_vercel
            if secure_cookies is None
            else secure_cookies.lower() in ("1", "true", "yes"),
        )


@cache
def local_timezone() -> ZoneInfo | None:
    """The timezone the users live in: ``TASKTRACKER_TIMEZONE``, e.g. ``Europe/Rome``.

    Unset means the server's own timezone. Hosts like Vercel run on UTC and don't let
    you change ``TZ``, so set this there, or timers and "today" are off by hours.
    """
    name = os.environ.get("TASKTRACKER_TIMEZONE")
    return ZoneInfo(name) if name else None
