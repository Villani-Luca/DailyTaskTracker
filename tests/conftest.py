from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tasktracker.config import Settings
from tasktracker.main import create_app


@pytest.fixture
def app() -> FastAPI:
    return create_app(Settings(database_url="sqlite://"))


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
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
