"""User accounts, passwords and login sessions.

Accounts are created by hand with ``tasktracker-users``; there is no sign-up. A login
session is a random token kept in a cookie; the database stores only its SHA-256, so a
leaked database does not hand out live sessions.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import timedelta
from functools import cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from tasktracker.models import LoginSession, User, now
from tasktracker.services.errors import ConflictError, InvalidOperationError

SESSION_LIFETIME = timedelta(days=30)
MIN_PASSWORD_LENGTH = 8
_USERNAME = re.compile(r"[a-z0-9][a-z0-9._@+-]{1,99}")

_hasher = PasswordHasher()  # argon2id with the RFC 9106 low-memory profile


def normalize_username(username: str) -> str:
    """Usernames are case-insensitive: ``Luca`` and ``luca`` are the same account."""
    return username.strip().lower()


def get_user(session: Session, username: str) -> User | None:
    return session.scalar(select(User).where(User.username == normalize_username(username)))


def list_users(session: Session) -> list[User]:
    return list(session.scalars(select(User).order_by(User.username)))


def create_user(session: Session, username: str, password: str) -> User:
    username = normalize_username(username)
    if not _USERNAME.fullmatch(username):
        raise InvalidOperationError(
            "A username is 2-100 characters: letters, digits and . _ @ + -, "
            "starting with a letter or digit"
        )
    if get_user(session, username) is not None:
        raise ConflictError(f"A user named {username!r} already exists")
    user = User(username=username, password_hash=hash_password(password))
    session.add(user)
    session.commit()
    return user


def set_password(session: Session, user: User, password: str) -> None:
    """Change a password and log the user out everywhere."""
    user.password_hash = hash_password(password)
    session.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    session.commit()


def authenticate(session: Session, username: str, password: str) -> User | None:
    user = get_user(session, username)
    if user is None:
        # Spend the same time as a real check, so response times don't reveal usernames.
        _verify_password(_dummy_hash(), password)
        return None
    if not _verify_password(user.password_hash, password):
        return None
    if _hasher.check_needs_rehash(user.password_hash):
        user.password_hash = _hasher.hash(password)
        session.commit()
    return user


# --- Login sessions ------------------------------------------------------------------


def start_session(session: Session, user_id: int) -> str:
    """Log a user in. Returns the token for the session cookie."""
    token = secrets.token_urlsafe(32)
    session.execute(
        delete(LoginSession).where(
            LoginSession.user_id == user_id, LoginSession.expires_at <= now()
        )
    )
    session.add(
        LoginSession(
            user_id=user_id, token_hash=_token_hash(token), expires_at=now() + SESSION_LIFETIME
        )
    )
    session.commit()
    return token


def user_for_token(session: Session, token: str) -> User | None:
    """The user a session token belongs to, or None if it is unknown or expired."""
    stmt = (
        select(User)
        .join(LoginSession, LoginSession.user_id == User.id)
        .where(LoginSession.token_hash == _token_hash(token), LoginSession.expires_at > now())
    )
    return session.scalar(stmt)


def end_session(session: Session, token: str) -> None:
    session.execute(delete(LoginSession).where(LoginSession.token_hash == _token_hash(token)))
    session.commit()


# --- Hashing -------------------------------------------------------------------------


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise InvalidOperationError(f"A password needs at least {MIN_PASSWORD_LENGTH} characters")
    return _hasher.hash(password)


def _verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


@cache
def _dummy_hash() -> str:
    return _hasher.hash(secrets.token_urlsafe(16))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
