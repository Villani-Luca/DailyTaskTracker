from datetime import date

from tasktracker.demo import seed_demo_data


def _stats_by_name(client, today="2026-09-25"):
    return {s["name"]: s for s in client.get("/api/folders/stats", params={"today": today}).json()}


def test_folder_stats_status_percentages(client, make_folder, make_task):
    work = make_folder("Work")
    make_folder("Empty")
    for status in ["todo", "todo", "in_progress", "done"]:
        make_task(folder_id=work["id"], status=status, estimate_minutes=30)

    stats = _stats_by_name(client)
    assert "Inbox" not in stats  # the inbox only shows up once it holds something

    work_stats = stats["Work"]
    assert work_stats["total_tasks"] == 4
    assert work_stats["open_tasks"] == 3
    assert work_stats["completion_percent"] == 25.0
    assert work_stats["estimate_minutes"] == 120
    by_status = {s["status"]: s for s in work_stats["statuses"]}
    assert by_status["todo"] == {"status": "todo", "count": 2, "percent": 50.0}
    assert by_status["blocked"]["count"] == 0

    empty = stats["Empty"]
    assert empty["total_tasks"] == 0
    assert empty["completion_percent"] == 0.0


def test_folder_stats_overdue_and_time(client, make_folder, make_task, make_block):
    work = make_folder("Work")
    late = make_task(folder_id=work["id"], planned_date="2026-09-20")
    make_task(folder_id=work["id"], due_date="2026-09-24", status="done")  # done: not overdue
    make_task("inbox task")
    make_block("2026-09-20T09:00", "2026-09-20T10:15", task_id=late["id"], kind="tracked")
    make_block("2026-09-21T09:00", "2026-09-21T09:30", title="Sync", folder_id=work["id"])

    stats = _stats_by_name(client)
    assert stats["Work"]["overdue_tasks"] == 1
    assert stats["Work"]["tracked_minutes"] == 75
    assert stats["Work"]["planned_minutes"] == 30
    assert stats["Inbox"]["total_tasks"] == 1


def test_overview_groups_tasks_by_day(client, make_folder, make_task, make_block):
    today = "2026-09-25"
    planned_today = make_task("planned today", planned_date=today)
    scheduled_tomorrow = make_task("scheduled tomorrow", planned_date="2026-09-30")
    make_block("2026-09-26T09:00", "2026-09-26T10:00", task_id=scheduled_tomorrow["id"])
    doing = make_task("doing", status="in_progress")
    late = make_task("late", planned_date="2026-09-20")
    make_task("later", planned_date="2026-10-15")

    overview = client.get("/api/overview", params={"today": today, "days": 2}).json()

    assert overview["today"] == today
    assert [d["day"] for d in overview["days"]] == ["2026-09-25", "2026-09-26", "2026-09-27"]
    day_titles = [[t["title"] for t in d["tasks"]] for d in overview["days"]]
    assert day_titles == [["planned today"], ["scheduled tomorrow"], []]
    assert overview["days"][1]["planned_minutes"] == 60
    assert [t["id"] for t in overview["active"]] == [doing["id"]]
    assert [t["id"] for t in overview["overdue"]] == [late["id"]]
    assert overview["running_timer"] is None
    assert planned_today["id"] not in [t["id"] for t in overview["overdue"]]


def test_time_report_clips_blocks_to_the_range(client, make_folder, make_task, make_block):
    work = make_folder("Work", "#2a78d6")
    task = make_task(folder_id=work["id"])
    # 2h tracked, but only the last hour falls inside the range
    make_block("2026-09-24T23:00", "2026-09-25T01:00", task_id=task["id"], kind="tracked")
    make_block("2026-09-25T10:00", "2026-09-25T10:45", title="Dentist")

    report = client.get(
        "/api/reports/time",
        params={"starts_at": "2026-09-25T00:00", "ends_at": "2026-09-26T00:00"},
    ).json()

    assert report["tracked_minutes"] == 60
    assert report["planned_minutes"] == 45
    rows = {r["name"]: r for r in report["folders"]}
    assert rows["Work"] == {
        "folder_id": work["id"],
        "name": "Work",
        "color": "#2a78d6",
        "planned_minutes": 0,
        "tracked_minutes": 60,
    }
    assert rows["Inbox"]["planned_minutes"] == 45


def test_demo_data_seeds_once(app, client):
    factory = app.state.session_factory
    assert seed_demo_data(factory, today=date(2026, 9, 25)) is True
    assert seed_demo_data(factory, today=date(2026, 9, 25)) is False

    stats = _stats_by_name(client)
    assert set(stats) == {"Work", "Personal", "Learning"}
    overview = client.get("/api/overview", params={"today": "2026-09-25"}).json()
    assert overview["days"][0]["tasks"]
