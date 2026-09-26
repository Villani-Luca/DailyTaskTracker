from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from tasktracker.api.deps import SESSION_COOKIE
from tasktracker.config import Settings
from tasktracker.main import create_app
from tasktracker.models import LoginSession, User, now
from tasktracker.services import auth
from tasktracker.services.errors import ConflictError, InvalidOperationError

DAY = {"starts_at": "2026-09-25T00:00", "ends_at": "2026-09-26T00:00"}
SLOT = {"starts_at": "2026-09-25T11:00", "ends_at": "2026-09-25T12:00"}


@pytest.fixture
def login(password):
    def _login(client, username="alice", password=password):
        return client.post("/api/auth/login", json={"username": username, "password": password})

    return _login


# --- Logging in and out --------------------------------------------------------------


def test_the_api_requires_a_login(anon_client):
    for path in ["/api/auth/me", "/api/folders", "/api/tasks", "/api/timer", "/api/overview"]:
        assert anon_client.get(path).status_code == 401, path
    assert anon_client.post("/api/folders", json={"name": "Work"}).status_code == 401


def test_pages_send_you_where_you_belong(anon_client, client):
    response = anon_client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    login_page = anon_client.get("/login")
    assert 'id="login-form"' in login_page.text

    assert client.get("/login", follow_redirects=False).headers["location"] == "/"
    # Which page you get depends on the cookie, so a cached copy would be wrong after logout.
    assert login_page.headers["cache-control"] == client.get("/").headers["cache-control"]
    assert login_page.headers["cache-control"] == "no-cache"


def test_login_me_and_logout(app, anon_client, make_user, login):
    make_user("alice")

    response = login(anon_client, username="  Alice ")  # usernames ignore case and spaces
    assert response.status_code == 200
    assert response.json()["username"] == "alice"
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "samesite=lax" in cookie.lower()
    assert "Secure" not in cookie
    assert anon_client.get("/api/auth/me").json()["username"] == "alice"
    assert anon_client.get("/api/folders").status_code == 200

    token = anon_client.cookies[SESSION_COOKIE]
    assert anon_client.post("/api/auth/logout").status_code == 204
    assert anon_client.get("/api/auth/me").status_code == 401
    # The session is gone on the server too, not just from the browser.
    with TestClient(app, cookies={SESSION_COOKIE: token}) as stale:
        assert stale.get("/api/auth/me").status_code == 401


def test_wrong_credentials_get_the_same_answer(anon_client, make_user, login):
    make_user("alice")
    wrong_password = login(anon_client, password="not the password")
    unknown_user = login(anon_client, username="mallory")

    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json()
    assert SESSION_COOKIE not in anon_client.cookies


def test_secure_cookies_setting(password_hash, login):
    app = create_app(Settings(database_url="sqlite://", secure_cookies=True))
    with app.state.session_factory() as session:
        session.add(User(username="alice", password_hash=password_hash))
        session.commit()

    with TestClient(app) as client:
        assert "Secure" in login(client).headers["set-cookie"]


def test_expired_sessions_are_rejected(app, client):
    with app.state.session_factory() as session:
        session.execute(update(LoginSession).values(expires_at=now() - timedelta(seconds=1)))
        session.commit()

    assert client.get("/api/auth/me").status_code == 401


def test_changing_a_password_logs_the_user_out_everywhere(app, client, user, anon_client, login):
    with app.state.session_factory() as session:
        auth.set_password(session, session.get(User, user.id), "a brand new password")

    assert client.get("/api/auth/me").status_code == 401
    assert login(anon_client).status_code == 401
    assert login(anon_client, password="a brand new password").status_code == 200


def test_create_user_rules(app):
    with app.state.session_factory() as session:
        user = auth.create_user(session, "  Luca ", "long enough")
        assert user.username == "luca"
        assert user.password_hash.startswith("$argon2id$")

        with pytest.raises(ConflictError):
            auth.create_user(session, "LUCA", "long enough")
        for bad_name in ["x", "has space", "-dash-first", "é"]:
            with pytest.raises(InvalidOperationError):
                auth.create_user(session, bad_name, "long enough")
        with pytest.raises(InvalidOperationError):
            auth.create_user(session, "carol", "short")


# --- Every user sees only their own records ------------------------------------------


@pytest.fixture
def alice_data(client, make_folder, make_task, make_block):
    """Alice (the default ``client``) has one of everything, and a timer running."""
    folder = make_folder("Work")
    task = make_task("Secret plan", folder_id=folder["id"])
    comment = client.post(f"/api/tasks/{task['id']}/comments", json={"body": "hush"}).json()
    block = make_block("2026-09-25T09:00", "2026-09-25T10:00", task_id=task["id"])
    meeting = make_block(
        "2026-09-25T14:00", "2026-09-25T15:00", title="1:1", folder_id=folder["id"]
    )
    client.post("/api/timer/start", json={"task_id": task["id"]})
    return {
        "folder": folder["id"],
        "task": task["id"],
        "comment": comment["id"],
        "block": block["id"],
        "meeting": meeting["id"],
    }


@pytest.fixture
def bob(make_user, client_for):
    return client_for(make_user("bob"))


def _assert_alice_data_untouched(client, ids):
    task = client.get(f"/api/tasks/{ids['task']}").json()
    assert task["status"] == "in_progress"
    assert task["folder_id"] == ids["folder"]
    assert task["comment_count"] == 1
    assert task["is_timer_running"] is True
    assert client.get(f"/api/folders/{ids['folder']}").json()["name"] == "Work"
    planned = client.get("/api/blocks", params={**DAY, "kind": "planned"}).json()
    assert [b["display_title"] for b in planned] == ["Secret plan", "1:1"]


def test_users_only_see_their_own_records(client, bob, alice_data):
    assert bob.get("/api/folders").json() == []
    assert bob.get("/api/folders/stats").json() == []
    assert bob.get("/api/tasks").json() == []
    assert bob.get("/api/blocks", params=DAY).json() == []
    assert bob.get("/api/reports/time", params=DAY).json()["folders"] == []
    assert bob.get("/api/timer").json() is None

    overview = bob.get("/api/overview", params={"today": "2026-09-25"}).json()
    assert overview["active"] == overview["overdue"] == []
    assert all(not day["tasks"] and not day["blocks"] for day in overview["days"])
    assert overview["running_timer"] is None

    # Each user has their own timer: Bob stopping "his" doesn't stop Alice's.
    assert bob.post("/api/timer/stop").json() is None
    _assert_alice_data_untouched(client, alice_data)


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/folders/{folder}", None),
        ("PATCH", "/api/folders/{folder}", lambda ids: {"name": "Mine now"}),
        ("DELETE", "/api/folders/{folder}", None),
        ("GET", "/api/tasks/{task}", None),
        ("PATCH", "/api/tasks/{task}", lambda ids: {"status": "done"}),
        ("DELETE", "/api/tasks/{task}", None),
        ("GET", "/api/tasks/{task}/blocks", None),
        ("GET", "/api/tasks/{task}/comments", None),
        ("POST", "/api/tasks/{task}/comments", lambda ids: {"body": "hi"}),
        ("DELETE", "/api/comments/{comment}", None),
        ("PATCH", "/api/blocks/{block}", lambda ids: {"title": "Mine now"}),
        ("DELETE", "/api/blocks/{meeting}", None),
        ("PATCH", "/api/blocks/{block}?scope=following", lambda ids: {"title": "Mine now"}),
        ("DELETE", "/api/blocks/{meeting}?scope=all", None),
        ("POST", "/api/tasks", lambda ids: {"title": "x", "folder_id": ids["folder"]}),
        ("POST", "/api/blocks", lambda ids: {**SLOT, "task_id": ids["task"]}),
        ("POST", "/api/blocks", lambda ids: {**SLOT, "title": "x", "folder_id": ids["folder"]}),
        ("POST", "/api/timer/start", lambda ids: {"task_id": ids["task"]}),
    ],
)
def test_other_users_records_look_like_they_do_not_exist(
    client, bob, alice_data, method, path, body
):
    response = bob.request(
        method, path.format(**alice_data), json=body(alice_data) if body else None
    )
    assert response.status_code == 404, response.text
    _assert_alice_data_untouched(client, alice_data)


def test_records_cannot_be_linked_to_another_users_records(client, bob, alice_data):
    task = bob.post("/api/tasks", json={"title": "Mine"}).json()
    block = bob.post("/api/blocks", json={**SLOT, "title": "Mine"}).json()

    assert (
        bob.patch(f"/api/tasks/{task['id']}", json={"folder_id": alice_data["folder"]})
    ).status_code == 404
    assert (
        bob.patch(f"/api/blocks/{block['id']}", json={"task_id": alice_data["task"]})
    ).status_code == 404
    assert (
        bob.patch(f"/api/blocks/{block['id']}", json={"folder_id": alice_data["folder"]})
    ).status_code == 404
    _assert_alice_data_untouched(client, alice_data)


def test_folder_names_are_unique_per_user(bob, alice_data):
    assert bob.post("/api/folders", json={"name": "Work"}).status_code == 201
    assert bob.post("/api/folders", json={"name": "work"}).status_code == 409
