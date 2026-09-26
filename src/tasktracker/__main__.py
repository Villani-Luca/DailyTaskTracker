"""Run the app: ``tasktracker`` or ``python -m tasktracker``."""

from __future__ import annotations

import argparse
import threading
import webbrowser

import uvicorn

from tasktracker.config import Settings
from tasktracker.db import init_db, make_engine, make_session_factory
from tasktracker.services import auth


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tasktracker", description="Daily Task Tracker")
    parser.add_argument("--host", help="interface to bind (default 127.0.0.1)")
    parser.add_argument("--port", type=int, help="port to listen on (default 8000)")
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    parser.add_argument("--reload", action="store_true", help="restart on code changes (dev)")
    parser.add_argument(
        "--demo",
        metavar="USERNAME",
        help="fill USERNAME's empty account with sample folders, tasks and calendar blocks",
    )
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    host = args.host or settings.host
    port = args.port or settings.port

    engine = make_engine(settings.database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as session:
        has_users = bool(auth.list_users(session))
        demo_user = auth.get_user(session, args.demo) if args.demo else None
    if args.demo:
        from tasktracker.demo import seed_demo_data

        if demo_user is None:
            parser.error(
                f"no user {args.demo!r}; create it with: tasktracker-users create {args.demo}"
            )
        seeded = seed_demo_data(session_factory, demo_user.id)
        print("Demo data added." if seeded else "That account already has data; demo skipped.")
    engine.dispose()

    print(f"Database: {settings.safe_database_url}")
    if not has_users:
        print("No users yet. Create one with: tasktracker-users create <username>")
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, args=(f"http://{host}:{port}",)).start()

    if args.reload:
        uvicorn.run("tasktracker.main:create_app", factory=True, host=host, port=port, reload=True)
    else:
        from tasktracker.main import create_app

        uvicorn.run(create_app(settings), host=host, port=port)


if __name__ == "__main__":
    main()
