from datetime import date, datetime

import pytest
from sqlalchemy import func, select

from tasktracker.models import Frequency, Recurrence
from tasktracker.services.errors import InvalidOperationError
from tasktracker.services.recurrence import MAX_EVENTS, occurrences

MONDAY_9AM = datetime(2026, 9, 28, 9, 0)
FOUR_WEEKS = {"starts_at": "2026-09-28T00:00", "ends_at": "2026-10-26T00:00"}


def _days(starts):
    return [s.date().isoformat() for s in starts]


# --- The rules -----------------------------------------------------------------------


def test_every_other_day():
    starts = occurrences(MONDAY_9AM, Frequency.DAILY, 2, [], date(2026, 10, 4))
    assert _days(starts) == ["2026-09-28", "2026-09-30", "2026-10-02", "2026-10-04"]
    assert {s.time() for s in starts} == {MONDAY_9AM.time()}


def test_every_other_week_on_chosen_days():
    wednesday = datetime(2026, 9, 30, 18, 0)
    starts = occurrences(wednesday, Frequency.WEEKLY, 2, [0, 2, 4], date(2026, 10, 16))
    # Monday 28 Sep came before the first event; the week of 5 Oct is skipped.
    assert _days(starts) == ["2026-09-30", "2026-10-02", "2026-10-12", "2026-10-14", "2026-10-16"]


def test_monthly_skips_months_without_that_day():
    starts = occurrences(datetime(2026, 1, 31, 8, 0), Frequency.MONTHLY, 1, [], date(2026, 6, 30))
    assert _days(starts) == ["2026-01-31", "2026-03-31", "2026-05-31"]


def test_limits():
    assert len(occurrences(MONDAY_9AM, Frequency.DAILY, 1, [], MONDAY_9AM.date())) == 1
    with pytest.raises(InvalidOperationError, match="on or after"):
        occurrences(MONDAY_9AM, Frequency.DAILY, 1, [], date(2026, 9, 27))
    with pytest.raises(InvalidOperationError, match=str(MAX_EVENTS)):
        occurrences(MONDAY_9AM, Frequency.DAILY, 1, [], date(2028, 9, 28))


# --- Series on the calendar ----------------------------------------------------------


def _blocks(client, **params):
    return client.get("/api/blocks", params={**FOUR_WEEKS, **params}).json()


@pytest.fixture
def standup(make_block):
    """Mondays and Wednesdays, 9:00-9:15, for four weeks: 8 events."""
    return make_block(
        "2026-09-28T09:00",
        "2026-09-28T09:15",
        title="Standup",
        recurrence={"frequency": "weekly", "weekdays": [0, 2], "until": "2026-10-21"},
    )


def test_each_event_of_a_series_is_a_block(client, standup):
    blocks = _blocks(client)
    assert [b["starts_at"][:10] for b in blocks] == [
        "2026-09-28", "2026-09-30", "2026-10-05", "2026-10-07",
        "2026-10-12", "2026-10-14", "2026-10-19", "2026-10-21",
    ]  # fmt: skip
    assert {(b["title"], b["starts_at"][11:16], b["ends_at"][11:16]) for b in blocks} == {
        ("Standup", "09:00", "09:15")
    }
    assert {b["recurrence"]["id"] for b in blocks} == {standup["recurrence"]["id"]}
    assert standup["recurrence"] | {"id": None} == {
        "id": None,
        "frequency": "weekly",
        "interval": 1,
        "weekdays": [0, 2],
        "until": "2026-10-21",
    }


def test_weekly_defaults_to_the_first_events_weekday(make_block):
    block = make_block(
        "2026-09-30T09:00",
        "2026-09-30T10:00",
        title="Review",
        recurrence={"frequency": "weekly", "until": "2026-10-14"},
    )
    assert block["recurrence"]["weekdays"] == [2]


def test_a_task_can_repeat_on_the_calendar(client, make_task, make_block):
    task = make_task("Deep work")
    make_block(
        "2026-09-28T14:00",
        "2026-09-28T16:00",
        task_id=task["id"],
        recurrence={"frequency": "daily", "until": "2026-10-02"},
    )
    refreshed = client.get(f"/api/tasks/{task['id']}").json()
    assert refreshed["planned_date"] == "2026-09-28"  # the first event's day
    assert refreshed["planned_minutes"] == 5 * 120


def test_repeat_rules_are_checked(client):
    slot = {"starts_at": "2026-09-28T09:00", "ends_at": "2026-09-28T10:00", "title": "x"}
    daily = {"frequency": "daily", "until": "2026-10-28"}
    tracked = client.post("/api/blocks", json={**slot, "kind": "tracked", "recurrence": daily})
    assert tracked.status_code == 422  # time already spent doesn't repeat
    ends_early = {"frequency": "daily", "until": "2026-09-27"}
    assert client.post("/api/blocks", json={**slot, "recurrence": ends_early}).status_code == 422
    too_many = {"frequency": "daily", "until": "2028-09-28"}
    assert client.post("/api/blocks", json={**slot, "recurrence": too_many}).status_code == 422
    assert _blocks(client) == []


def test_moving_one_event_leaves_the_others(client, standup):
    second = _blocks(client)[1]
    response = client.patch(
        f"/api/blocks/{second['id']}",
        json={"starts_at": "2026-09-30T10:00", "ends_at": "2026-09-30T10:15"},
    )
    assert response.json()["recurrence"] is not None  # still part of the series

    assert [b["starts_at"][11:16] for b in _blocks(client)] == ["09:00", "10:00"] + ["09:00"] * 6


def test_changing_this_and_the_following_events(client, standup):
    third = _blocks(client)[2]
    response = client.patch(
        f"/api/blocks/{third['id']}",
        params={"scope": "following"},
        json={"title": "Sync", "starts_at": "2026-10-05T09:30", "ends_at": "2026-10-05T10:00"},
    )
    assert response.status_code == 200, response.text

    blocks = _blocks(client)
    assert [(b["title"], b["starts_at"][11:16]) for b in blocks] == (
        [("Standup", "09:00")] * 2 + [("Sync", "09:30")] * 6
    )
    earlier, later = blocks[0]["recurrence"], blocks[2]["recurrence"]
    assert earlier["until"] == "2026-10-04"  # the old series ends before the change
    assert later["id"] != earlier["id"]
    assert (later["weekdays"], later["until"]) == ([0, 2], "2026-10-21")


def test_changing_how_the_following_events_repeat(client, standup):
    third = _blocks(client)[2]
    fridays = {"frequency": "weekly", "weekdays": [4], "until": "2026-10-23"}
    client.patch(
        f"/api/blocks/{third['id']}", params={"scope": "following"}, json={"recurrence": fridays}
    )
    assert [b["starts_at"][:10] for b in _blocks(client)] == [
        "2026-09-28", "2026-09-30", "2026-10-05", "2026-10-09", "2026-10-16", "2026-10-23",
    ]  # fmt: skip


def test_stop_repeating_after_an_event(client, standup):
    third = _blocks(client)[2]
    client.patch(
        f"/api/blocks/{third['id']}", params={"scope": "following"}, json={"recurrence": None}
    )
    blocks = _blocks(client)
    assert len(blocks) == 3
    assert blocks[2]["recurrence"] is None
    assert blocks[0]["recurrence"]["until"] == "2026-10-04"


def test_how_a_series_repeats_changes_for_the_following_events_only(client, standup):
    daily = {"frequency": "daily", "until": "2026-10-01"}
    url = f"/api/blocks/{standup['id']}"
    assert client.patch(url, json={"recurrence": daily}).status_code == 422
    assert client.patch(url, params={"scope": "all"}, json={"title": "x"}).status_code == 422


def test_a_single_block_can_start_repeating(client, make_block):
    gym = make_block("2026-09-28T18:00", "2026-09-28T19:00", title="Gym")
    response = client.patch(
        f"/api/blocks/{gym['id']}",
        json={"recurrence": {"frequency": "weekly", "until": "2026-10-19"}},
    )
    assert response.json()["recurrence"]["weekdays"] == [0]
    assert [b["starts_at"][:10] for b in _blocks(client)] == [
        "2026-09-28", "2026-10-05", "2026-10-12", "2026-10-19",
    ]  # fmt: skip


@pytest.mark.parametrize(("scope", "left"), [("this", 7), ("following", 2), ("all", 1)])
def test_deleting_events_of_a_series(client, standup, scope, left):
    blocks = _blocks(client)
    client.patch(f"/api/blocks/{blocks[0]['id']}", json={"kind": "tracked"})  # it happened

    response = client.delete(f"/api/blocks/{blocks[2]['id']}", params={"scope": scope})
    assert response.status_code == 204
    remaining = _blocks(client)
    assert len(remaining) == left
    assert remaining[0]["kind"] == "tracked"  # time spent is never deleted with the series


def test_a_series_without_events_is_removed(app, client, standup):
    client.delete(f"/api/blocks/{standup['id']}", params={"scope": "all"})
    with app.state.session_factory() as session:
        assert session.scalar(select(func.count(Recurrence.id))) == 0
