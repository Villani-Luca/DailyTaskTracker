"""FastAPI application factory."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from tasktracker import __version__
from tasktracker.api import api_router
from tasktracker.api.deps import OptionalUser
from tasktracker.config import Settings, local_timezone
from tasktracker.db import init_db, make_engine, make_session_factory
from tasktracker.services.errors import (
    ConflictError,
    DomainError,
    InvalidOperationError,
    NotFoundError,
)

STATIC_DIR = Path(__file__).parent / "static"

_ERROR_STATUS = {NotFoundError: 404, ConflictError: 409, InvalidOperationError: 422}
_NO_CACHE = {"Cache-Control": "no-cache"}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    local_timezone()  # a misspelled TASKTRACKER_TIMEZONE fails here, not on first request
    engine = make_engine(settings.database_url)
    init_db(engine)

    app = FastAPI(title="Daily Task Tracker", version=__version__)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)

    @app.exception_handler(DomainError)
    async def _domain_error(_request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=_ERROR_STATUS.get(type(exc), 400))

    app.include_router(api_router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # The pages are public files; only /api needs a login. Redirecting here just saves a
    # round trip: the app itself also sends you to /login when the API says 401. The
    # answer depends on the login cookie, so browsers must ask every time, not cache it.
    @app.get("/", include_in_schema=False)
    def index(user: OptionalUser) -> Response:
        if user is None:
            return RedirectResponse("/login", status_code=303)
        return FileResponse(STATIC_DIR / "index.html", headers=_NO_CACHE)

    @app.get("/login", include_in_schema=False)
    def login_page(user: OptionalUser) -> Response:
        if user is not None:
            return RedirectResponse("/", status_code=303)
        return FileResponse(STATIC_DIR / "login.html", headers=_NO_CACHE)

    return app
