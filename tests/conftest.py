from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import ExitStack
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tasktracker.api.deps import SESSION_COOKIE
from tasktracker.config import Settings
from tasktracker.main import create_app
from tasktracker.models import User
from tasktracker.services import auth

PASSWORD = "correct horse battery staple"


@pytest.fixture(scope="session")
def password() -> str:
    """Every test user's password."""
    return PASSWORD


@pytest.fixture(scope="session")
def password_hash() -> str:
    # Hashing is slow on purpose; do it once and share the result between test users.
    return auth.hash_password(PASSWORD)


@pytest.fixture
def app() -> FastAPI:
    return create_app(Settings(database_url="sqlite://"))


@pytest.fixture
def make_user(app: FastAPI, password_hash: str) -> Callable[[str], User]:
    """Add a user whose password is the ``password`` fixture."""

    def _make(username: str) -> User:
        with app.state.session_factory() as session:
            user = User(username=username, password_hash=password_hash)
            session.add(user)
            session.commit()
            return user

    return _make


@pytest.fixture
def client_for(app: FastAPI) -> Iterator[Callable[[User], TestClient]]:
    """A client that is already logged in as ``user``."""
    with ExitStack() as stack:

        def _client(user: User) -> TestClient:
            with app.state.session_factory() as session:
                token = auth.start_session(session, user.id)
            return stack.enter_context(TestClient(app, cookies={SESSION_COOKIE: token}))

        yield _client


@pytest.fixture
def user(make_user: Callable[[str], User]) -> User:
    return make_user("alice")


@pytest.fixture
def client(client_for: Callable[[User], TestClient], user: User) -> TestClient:
    return client_for(user)


@pytest.fixture
def anon_client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def make_folder(client: TestClient) -> Callable[..., dict[str, Any]]:
    def _make(name: str = "Work", color: str = "#2a78d6", **extra: Any) -> dict[str, Any]:
        response = client.post("/api/folders", json={"name": name, "color": color, **extra})
        assert response.status_code == 201, response.text
        return response.json()

    return _make


@pytest.fixture
def make_task(client: TestClient) -> Callable[..., dict[str, Any]]:
    def _make(title: str = "Task", **fields: Any) -> dict[str, Any]:
        response = client.post("/api/tasks", json={"title": title, **fields})
        assert response.status_code == 201, response.text
        return response.json()

    return _make


@pytest.fixture
def make_block(client: TestClient) -> Callable[..., dict[str, Any]]:
    def _make(starts_at: str, ends_at: str, **fields: Any) -> dict[str, Any]:
        response = client.post(
            "/api/blocks", json={"starts_at": starts_at, "ends_at": ends_at, **fields}
        )
        assert response.status_code == 201, response.text
        return response.json()

    return _make
