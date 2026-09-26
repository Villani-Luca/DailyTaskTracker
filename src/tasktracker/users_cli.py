"""Manage user accounts: ``tasktracker-users create | set-password | list``.

There is no sign-up page: accounts are created here, by hand. The script uses the same
database as the app (``TASKTRACKER_DATABASE_URL``), so in production run it with the
same environment as the server, for example inside its container.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from tasktracker.config import Settings
from tasktracker.db import init_db, make_engine, make_session_factory
from tasktracker.services import auth
from tasktracker.services.errors import DomainError


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="tasktracker-users", description="Manage Daily Task Tracker user accounts."
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    for name, help_text in [
        ("create", "create a user (asks for the password)"),
        ("set-password", "change a user's password and log them out everywhere"),
    ]:
        command = commands.add_parser(name, help=help_text, description=help_text)
        command.add_argument("username")
        command.add_argument(
            "--password-stdin",
            action="store_true",
            help="read the password from standard input instead of asking for it",
        )
    commands.add_parser("list", help="list all users", description="list all users")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    print(f"Database: {settings.safe_database_url}")
    engine = make_engine(settings.database_url)
    init_db(engine)
    try:
        with make_session_factory(engine)() as session:
            if args.command == "list":
                users = auth.list_users(session)
                for user in users:
                    print(f"{user.username}  (created {user.created_at:%Y-%m-%d})")
                if not users:
                    print("No users yet.")
                return

            # Check the username before asking for a password that would be thrown away.
            user = auth.get_user(session, args.username)
            if args.command == "create":
                if user is not None:
                    sys.exit(f"error: a user named {user.username!r} already exists")
                user = auth.create_user(session, args.username, _read_password(args))
                print(f"Created user {user.username!r}.")
            else:
                if user is None:
                    sys.exit(f"error: no user named {args.username!r}")
                auth.set_password(session, user, _read_password(args))
                print(f"Password changed for {user.username!r}; their sessions were ended.")
    except DomainError as exc:
        sys.exit(f"error: {exc}")
    finally:
        engine.dispose()


def _read_password(args: argparse.Namespace) -> str:
    if args.password_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    password = getpass.getpass("Password: ")
    if getpass.getpass("Repeat password: ") != password:
        sys.exit("error: the passwords do not match")
    return password


if __name__ == "__main__":
    main()
