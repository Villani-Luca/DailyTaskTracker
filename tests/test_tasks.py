from tasktracker.models import INBOX_COLOR


def test_task_takes_its_folder_color(make_folder, make_task):
    folder = make_folder(color="#eb6834")
    assert make_task(folder_id=folder["id"])["color"] == "#eb6834"
    assert make_task()["color"] == INBOX_COLOR


def test_create_task_in_unknown_folder_is_404(client):
    response = client.post("/api/tasks", json={"title": "x", "folder_id": 999})
    assert response.status_code == 404


def test_completing_and_reopening_a_task(client, make_task):
    task = make_task()
    assert task["completed_at"] is None

    done = client.patch(f"/api/tasks/{task['id']}", json={"status": "done"}).json()
    assert done["status"] == "done"
    assert done["completed_at"] is not None

    reopened = client.patch(f"/api/tasks/{task['id']}", json={"status": "todo"}).json()
    assert reopened["completed_at"] is None


def test_patch_can_clear_nullable_fields_but_not_required_ones(client, make_task):
    task = make_task(planned_date="2026-09-25", estimate_minutes=30)

    cleared = client.patch(f"/api/tasks/{task['id']}", json={"planned_date": None}).json()
    assert cleared["planned_date"] is None
    assert cleared["estimate_minutes"] == 30  # untouched

    response = client.patch(f"/api/tasks/{task['id']}", json={"title": None})
    assert response.status_code == 422


def test_list_tasks_filters(client, make_folder, make_task):
    work = make_folder("Work")
    a = make_task("Write report", folder_id=work["id"], status="in_progress")
    b = make_task("Review report", folder_id=work["id"], status="done")
    c = make_task("Buy milk")

    def ids(**params):
        return {t["id"] for t in client.get("/api/tasks", params=params).json()}

    assert ids(folder_id=work["id"]) == {a["id"], b["id"]}
    assert ids(inbox=True) == {c["id"]}
    assert ids(status=["in_progress", "todo"]) == {a["id"], c["id"]}
    assert ids(q="REPORT") == {a["id"], b["id"]}


def test_list_tasks_puts_work_in_progress_first_and_done_last(client, make_task):
    done = make_task("done", status="done")
    todo = make_task("todo")
    doing = make_task("doing", status="in_progress")
    order = [t["id"] for t in client.get("/api/tasks").json()]
    assert order == [doing["id"], todo["id"], done["id"]]


def test_comments(client, make_task):
    task = make_task()
    url = f"/api/tasks/{task['id']}/comments"

    first = client.post(url, json={"body": "  First thought  "}).json()
    client.post(url, json={"body": "Second thought"})
    assert first["body"] == "First thought"
    assert [c["body"] for c in client.get(url).json()] == ["First thought", "Second thought"]
    assert client.get(f"/api/tasks/{task['id']}").json()["comment_count"] == 2

    assert client.delete(f"/api/comments/{first['id']}").status_code == 204
    assert [c["body"] for c in client.get(url).json()] == ["Second thought"]

    assert client.post(url, json={"body": "   "}).status_code == 422
    assert client.post("/api/tasks/999/comments", json={"body": "x"}).status_code == 404


def test_deleting_a_task_removes_its_comments_and_blocks(client, make_task, make_block):
    task = make_task()
    client.post(f"/api/tasks/{task['id']}/comments", json={"body": "note"})
    make_block("2026-09-25T09:00", "2026-09-25T10:00", task_id=task["id"])

    assert client.delete(f"/api/tasks/{task['id']}").status_code == 204
    assert client.get(f"/api/tasks/{task['id']}").status_code == 404
    blocks = client.get(
        "/api/blocks", params={"starts_at": "2026-09-25T00:00", "ends_at": "2026-09-26T00:00"}
    ).json()
    assert blocks == []
