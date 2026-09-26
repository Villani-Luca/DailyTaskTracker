import io

import pytest
from fastapi.testclient import TestClient

from tasktracker import users_cli
from tasktracker.config import Settings
from tasktracker.main import create_app


@pytest.fixture
def database_url(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'tasks.db').as_posix()}"
    monkeypatch.setenv("TASKTRACKER_DATABASE_URL", url)
    return url


def _stdin(monkeypatch, text):
    monkeypatch.setattr("sys.stdin", io.StringIO(text))


def _can_log_in(database_url, username, password):
    app = create_app(Settings(database_url=database_url))
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/auth/login", json={"username": username, "password": password}
            )
            return response.status_code == 200
    finally:
        app.state.engine.dispose()


def test_create_list_and_set_password(database_url, monkeypatch, capsys):
    _stdin(monkeypatch, "first password\n")
    users_cli.main(["create", "Luca", "--password-stdin"])
    assert "Created user 'luca'" in capsys.readouterr().out

    users_cli.main(["list"])
    assert "luca  (created " in capsys.readouterr().out
    assert _can_log_in(database_url, "luca", "first password")

    _stdin(monkeypatch, "second password\n")
    users_cli.main(["set-password", "luca", "--password-stdin"])
    assert _can_log_in(database_url, "luca", "second password")
    assert not _can_log_in(database_url, "luca", "first password")


def test_password_prompt_must_match(database_url, monkeypatch):
    answers = iter(["first password", "a typo"])
    monkeypatch.setattr("getpass.getpass", lambda prompt: next(answers))

    with pytest.raises(SystemExit, match="do not match"):
        users_cli.main(["create", "luca"])


def test_errors_exit_with_a_message(database_url, monkeypatch):
    _stdin(monkeypatch, "first password\n")
    users_cli.main(["create", "luca", "--password-stdin"])

    with pytest.raises(SystemExit, match="already exists"):
        users_cli.main(["create", "LUCA", "--password-stdin"])
    with pytest.raises(SystemExit, match="no user named"):
        users_cli.main(["set-password", "nobody", "--password-stdin"])
    _stdin(monkeypatch, "short\n")
    with pytest.raises(SystemExit, match="at least 8 characters"):
        users_cli.main(["create", "carol", "--password-stdin"])
