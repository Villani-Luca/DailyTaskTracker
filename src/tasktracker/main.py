"""FastAPI application factory."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from tasktracker import __version__
from tasktracker.api import api_router
from tasktracker.config import Settings
from tasktracker.db import init_db, make_engine, make_session_factory
from tasktracker.services.errors import (
    ConflictError,
    DomainError,
    InvalidOperationError,
    NotFoundError,
)

STATIC_DIR = Path(__file__).parent / "static"

_ERROR_STATUS = {NotFoundError: 404, ConflictError: 409, InvalidOperationError: 422}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    engine = make_engine(settings.database_url)
    init_db(engine)

    app = FastAPI(title="Daily Task Tracker", version=__version__)
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)

    @app.exception_handler(DomainError)
    async def _domain_error(_request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=_ERROR_STATUS.get(type(exc), 400))

    app.include_router(api_router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app
