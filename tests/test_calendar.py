DAY = {"starts_at": "2026-09-25T00:00", "ends_at": "2026-09-26T00:00"}


def test_blocks_are_colored_by_folder_and_follow_color_changes(
    client, make_folder, make_task, make_block
):
    folder = make_folder(color="#2a78d6")
    task = make_task("Slides", folder_id=folder["id"])
    task_block = make_block("2026-09-25T09:00", "2026-09-25T10:00", task_id=task["id"])
    meeting = make_block(
        "2026-09-25T14:00", "2026-09-25T15:00", title="Standup", folder_id=folder["id"]
    )
    assert task_block["color"] == meeting["color"] == "#2a78d6"
    assert task_block["display_title"] == "Slides"
    assert task_block["effective_folder_id"] == folder["id"]

    client.patch(f"/api/folders/{folder['id']}", json={"color": "#eb6834"})

    colors = {b["color"] for b in client.get("/api/blocks", params=DAY).json()}
    assert colors == {"#eb6834"}


def test_list_blocks_returns_blocks_overlapping_the_range(client, make_block):
    make_block("2026-09-24T23:00", "2026-09-25T01:00", title="Overnight")
    make_block("2026-09-25T12:00", "2026-09-25T13:00", title="Lunch")
    make_block("2026-09-26T00:00", "2026-09-26T01:00", title="Tomorrow")

    titles = [b["title"] for b in client.get("/api/blocks", params=DAY).json()]
    assert titles == ["Overnight", "Lunch"]


def test_block_validation(client, make_task):
    task = make_task()
    backwards = {"starts_at": "2026-09-25T10:00", "ends_at": "2026-09-25T09:00"}
    assert client.post("/api/blocks", json={**backwards, "task_id": task["id"]}).status_code == 422

    untitled = {"starts_at": "2026-09-25T09:00", "ends_at": "2026-09-25T10:00"}
    assert client.post("/api/blocks", json=untitled).status_code == 422
    assert client.post("/api/blocks", json={**untitled, "task_id": 999}).status_code == 404


def test_patch_block_rejects_end_before_start(client, make_block):
    block = make_block("2026-09-25T09:00", "2026-09-25T10:00", title="Call")
    response = client.patch(f"/api/blocks/{block['id']}", json={"ends_at": "2026-09-25T08:00"})
    assert response.status_code == 422


def test_timezone_aware_input_is_stored_as_local_time(make_block):
    block = make_block("2026-09-25T09:00:00Z", "2026-09-25T10:00:00Z", title="Call")
    assert not block["starts_at"].endswith(("+00:00", "Z"))
    assert block["duration_minutes"] == 60


def test_placing_a_task_on_the_calendar_plans_it_for_that_day(client, make_task, make_block):
    task = make_task()
    block = make_block("2026-09-25T09:00", "2026-09-25T10:00", task_id=task["id"])
    assert client.get(f"/api/tasks/{task['id']}").json()["planned_date"] == "2026-09-25"

    # Dragging the block to another day moves the plan along with it...
    client.patch(
        f"/api/blocks/{block['id']}",
        json={"starts_at": "2026-09-28T09:00", "ends_at": "2026-09-28T10:00"},
    )
    assert client.get(f"/api/tasks/{task['id']}").json()["planned_date"] == "2026-09-28"


def test_a_deliberately_chosen_planned_date_is_not_overwritten(client, make_task, make_block):
    task = make_task(planned_date="2026-09-30")
    make_block("2026-09-25T09:00", "2026-09-25T10:00", task_id=task["id"])
    assert client.get(f"/api/tasks/{task['id']}").json()["planned_date"] == "2026-09-30"


def test_marking_a_planned_block_as_spent_counts_as_tracked_time(client, make_task, make_block):
    task = make_task()
    block = make_block("2026-09-25T09:00", "2026-09-25T10:30", task_id=task["id"])
    assert client.get(f"/api/tasks/{task['id']}").json()["planned_minutes"] == 90

    client.patch(f"/api/blocks/{block['id']}", json={"kind": "tracked"})

    refreshed = client.get(f"/api/tasks/{task['id']}").json()
    assert refreshed["planned_minutes"] == 0
    assert refreshed["tracked_minutes"] == 90


def test_unlinking_a_block_from_its_task_keeps_it_as_an_appointment(client, make_task, make_block):
    task = make_task()
    block = make_block("2026-09-25T09:00", "2026-09-25T10:00", task_id=task["id"])

    response = client.patch(
        f"/api/blocks/{block['id']}", json={"task_id": None, "title": "Focus time"}
    )
    assert response.status_code == 200
    assert response.json()["task_id"] is None
    assert [b["title"] for b in client.get("/api/blocks", params=DAY).json()] == ["Focus time"]


def test_timer_start_stop(client, make_task):
    task = make_task()
    assert client.get("/api/timer").json() is None

    started = client.post("/api/timer/start", json={"task_id": task["id"]}).json()
    assert started["is_running"] is True
    assert started["kind"] == "tracked"
    assert client.get("/api/timer").json()["id"] == started["id"]

    refreshed = client.get(f"/api/tasks/{task['id']}").json()
    assert refreshed["status"] == "in_progress"
    assert refreshed["is_timer_running"] is True

    stopped = client.post("/api/timer/stop").json()
    assert stopped["id"] == started["id"]
    assert stopped["is_running"] is False
    assert client.get("/api/timer").json() is None
    assert client.post("/api/timer/stop").json() is None


def test_only_one_timer_runs_at_a_time(client, make_task):
    first, second = make_task("first"), make_task("second")
    a = client.post("/api/timer/start", json={"task_id": first["id"]}).json()
    again = client.post("/api/timer/start", json={"task_id": first["id"]}).json()
    assert again["id"] == a["id"]

    b = client.post("/api/timer/start", json={"task_id": second["id"]}).json()
    assert client.get("/api/timer").json()["id"] == b["id"]
    assert client.get(f"/api/tasks/{first['id']}").json()["is_timer_running"] is False


def test_completing_a_task_stops_its_timer(client, make_task):
    task = make_task()
    client.post("/api/timer/start", json={"task_id": task["id"]})
    client.patch(f"/api/tasks/{task['id']}", json={"status": "done"})
    assert client.get("/api/timer").json() is None
