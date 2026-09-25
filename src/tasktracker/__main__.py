"""Run the app: ``tasktracker`` or ``python -m tasktracker``."""

from __future__ import annotations

import argparse
import threading
import webbrowser

import uvicorn

from tasktracker.config import Settings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tasktracker", description="Daily Task Tracker")
    parser.add_argument("--host", help="interface to bind (default 127.0.0.1)")
    parser.add_argument("--port", type=int, help="port to listen on (default 8000)")
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    parser.add_argument("--reload", action="store_true", help="restart on code changes (dev)")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="fill an empty database with sample folders, tasks and calendar blocks",
    )
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    host = args.host or settings.host
    port = args.port or settings.port

    if args.demo:
        from tasktracker.db import init_db, make_engine, make_session_factory
        from tasktracker.demo import seed_demo_data

        engine = make_engine(settings.database_url)
        init_db(engine)
        seeded = seed_demo_data(make_session_factory(engine))
        print("Demo data added." if seeded else "Database already has data; demo data skipped.")

    print(f"Database: {settings.database_url}")
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, args=(f"http://{host}:{port}",)).start()

    if args.reload:
        uvicorn.run("tasktracker.main:create_app", factory=True, host=host, port=port, reload=True)
    else:
        from tasktracker.main import create_app

        uvicorn.run(create_app(settings), host=host, port=port)


if __name__ == "__main__":
    main()
