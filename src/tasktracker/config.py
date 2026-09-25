"""Runtime settings, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DB_PATH = Path.home() / ".dailytasktracker" / "tasks.db"


@dataclass(frozen=True)
class Settings:
    database_url: str
    host: str = "127.0.0.1"
    port: int = 8000

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            database_url=os.environ.get(
                "TASKTRACKER_DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH.as_posix()}"
            ),
            host=os.environ.get("TASKTRACKER_HOST", "127.0.0.1"),
            port=int(os.environ.get("TASKTRACKER_PORT", "8000")),
        )
