"""Importing appointments from .ics files, emails, pasted text and links."""

import base64
from datetime import datetime

import pytest
from sqlalchemy import create_engine, inspect, text

from tasktracker.config import local_timezone
from tasktracker.db import init_db
from tasktracker.services import imports

NOW = datetime(2026, 9, 26, 12, 0)


@pytest.fixture(autouse=True)
def rome_and_fixed_now(monkeypatch):
    monkeypatch.setenv("TASKTRACKER_TIMEZONE", "Europe/Rome")
    local_timezone.cache_clear()
    monkeypatch.setattr(imports, "now", lambda: NOW)
    yield
    local_timezone.cache_clear()


def ics(*events: str, method: str = "PUBLISH") -> str:
    body = "\r\n".join(events)
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//EN\r\n"
        f"METHOD:{method}\r\n{body}\r\nEND:VCALENDAR\r\n"
    )


def vevent(uid: str, summary: str, start: str, end: str, *extra: str) -> str:
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"SUMMARY:{summary}",
        start if ":" in start else f"DTSTART;TZID=Europe/Rome:{start}",
        end if ":" in end else f"DTEND;TZID=Europe/Rome:{end}",
        *extra,
        "END:VEVENT",
    ]
    return "\r\n".join(lines)


def blocks_between(client, start="2026-01-01T00:00", end="2028-01-01T00:00"):
    return client.get("/api/blocks", params={"starts_at": start, "ends_at": end}).json()


def do_import(client, content, filename="invite.ics", **extra):
    response = client.post("/api/import", json={"content": content, "filename": filename, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def test_an_ics_event_becomes_an_appointment_in_the_chosen_folder(client, make_folder):
    folder = make_folder("Client X", color="#eb6834")
    content = ics(
        vevent(
            "kickoff-1",
            "Kickoff\\, phase 2",
            "20261001T100000",
            "20261001T113000",
            "LOCATION:Room 4\\, Milan office",
            "DESCRIPTION:Agenda:\\n1. Scope\\n2. Dates",
            "ORGANIZER;CN=Anna Rossi:mailto:anna@example.com",
            "ATTENDEE;CN=Luca:mailto:luca@example.com",
        )
    )

    preview = client.post("/api/import/preview", json={"content": content, "filename": "k.ics"})
    assert preview.status_code == 200, preview.text
    [event] = preview.json()["events"]
    assert event["status"] == "new"
    assert event["title"] == "Kickoff, phase 2"
    assert event["starts_at"] == "2026-10-01T10:00:00"
    assert event["events"] == 1
    assert blocks_between(client) == []  # a preview saves nothing

    result = do_import(client, content, filename="k.ics", folder_id=folder["id"])
    assert result["added"] == 1 and result["blocks"] == 1

    [block] = blocks_between(client)
    assert block["title"] == "Kickoff, phase 2"
    assert block["folder_id"] == folder["id"]
    assert block["color"] == "#eb6834"
    assert block["kind"] == "planned"
    assert block["ends_at"] == "2026-10-01T11:30:00"
    assert block["location"] == "Room 4, Milan office"
    assert block["source"] == "k.ics"
    assert "Agenda:\n1. Scope" in block["notes"]
    assert "Organizer: Anna Rossi <anna@example.com>" in block["notes"]
    assert "Attendees: Luca <luca@example.com>" in block["notes"]


def test_times_are_converted_to_local_time(client):
    content = ics(
        vevent("utc", "UTC call", "DTSTART:20261001T090000Z", "DTEND:20261001T100000Z"),
        vevent(
            "outlook",
            "Outlook call",
            "DTSTART;TZID=Eastern Standard Time:20261002T090000",
            "DTEND;TZID=Eastern Standard Time:20261002T093000",
        ),
        vevent("floating", "Floating", "DTSTART:20261003T090000", "DURATION:PT45M"),
    )
    do_import(client, content)
    starts = {b["title"]: (b["starts_at"], b["ends_at"]) for b in blocks_between(client)}
    assert starts["UTC call"] == ("2026-10-01T11:00:00", "2026-10-01T12:00:00")
    assert starts["Outlook call"] == ("2026-10-02T15:00:00", "2026-10-02T15:30:00")
    assert starts["Floating"] == ("2026-10-03T09:00:00", "2026-10-03T09:45:00")


def test_a_repeating_event_becomes_a_series_in_the_folder(client, make_folder):
    folder = make_folder("Team")
    content = ics(
        vevent(
            "standup",
            "Standup",
            "20261005T093000",
            "20261005T094500",
            "RRULE:FREQ=WEEKLY;BYDAY=MO,WE;COUNT=6",
            "EXDATE;TZID=Europe/Rome:20261012T093000",
        )
    )
    [event] = client.post("/api/import/preview", json={"content": content}).json()["events"]
    assert event["recurrence"]["frequency"] == "weekly"
    assert event["recurrence"]["weekdays"] == [0, 2]
    assert event["events"] == 5  # six, one of them excluded

    do_import(client, content, folder_id=folder["id"])
    blocks = blocks_between(client)
    assert [b["starts_at"][:10] for b in blocks] == [
        "2026-10-05",
        "2026-10-07",
        "2026-10-14",
        "2026-10-19",
        "2026-10-21",
    ]
    assert {b["folder_id"] for b in blocks} == {folder["id"]}
    assert len({b["recurrence"]["id"] for b in blocks}) == 1

    # The folder lists the series once.
    [appointment] = client.get("/api/appointments", params={"folder_id": folder["id"]}).json()
    assert appointment["events"] == 5
    assert appointment["upcoming"] == 5
    assert appointment["block"]["starts_at"] == "2026-10-05T09:30:00"
    assert appointment["planned_minutes"] == 5 * 15

    # And it works like any series made in the app: delete them all at once.
    client.delete(f"/api/blocks/{blocks[0]['id']}", params={"scope": "all"})
    assert blocks_between(client) == []


def test_every_weekday_and_yearly_rules(client):
    content = ics(
        vevent(
            "weekdays",
            "Focus",
            "20261005T080000",
            "20261005T090000",
            "RRULE:FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR;UNTIL=20261011T235959Z",
        ),
        vevent(
            "yearly",
            "Review",
            "20261010T150000",
            "20261010T160000",
            "RRULE:FREQ=YEARLY;COUNT=2",
        ),
    )
    do_import(client, content)
    days = [b["starts_at"][:10] for b in blocks_between(client, end="2028-01-01T00:00")]
    assert days == [
        "2026-10-05",
        "2026-10-06",
        "2026-10-07",
        "2026-10-08",
        "2026-10-09",
        "2026-10-10",
        "2027-10-10",
    ]


def test_a_rule_that_cannot_be_a_series_imports_one_event_and_says_so(client):
    content = ics(
        vevent(
            "second-tuesday",
            "Board",
            "20261013T100000",
            "20261013T110000",
            "RRULE:FREQ=MONTHLY;BYDAY=2TU",
        )
    )
    [event] = client.post("/api/import/preview", json={"content": content}).json()["events"]
    assert event["recurrence"] is None
    assert event["events"] == 1
    assert "only one event" in event["warnings"][0]


def test_a_series_without_end_is_imported_for_a_year(client):
    content = ics(
        vevent("daily", "Daily", "20261001T090000", "20261001T091500", "RRULE:FREQ=DAILY")
    )
    [event] = client.post("/api/import/preview", json={"content": content}).json()["events"]
    assert event["recurrence"]["until"] == "2027-10-01"
    assert "no end" in event["warnings"][0]


def test_past_events_are_skipped_unless_asked_for(client):
    content = ics(
        vevent("old", "Old meeting", "20260901T100000", "20260901T110000"),
        vevent(
            "weekly",
            "Weekly sync",
            "20260907T100000",
            "20260907T110000",
            "RRULE:FREQ=WEEKLY;UNTIL=20261019T235959Z",
        ),
    )
    preview = client.post("/api/import/preview", json={"content": content}).json()
    by_title = {e["title"]: e for e in preview["events"]}
    assert by_title["Old meeting"]["events"] == 0
    assert by_title["Old meeting"]["past_events"] == 1
    assert by_title["Weekly sync"]["events"] == 4  # 28 Sep to 19 Oct
    assert by_title["Weekly sync"]["past_events"] == 3

    do_import(client, content)
    days = [b["starts_at"][:10] for b in blocks_between(client)]
    assert days == ["2026-09-28", "2026-10-05", "2026-10-12", "2026-10-19"]


def test_past_events_can_be_included(client):
    content = ics(
        vevent("weekly", "Sync", "20260907T100000", "20260907T110000", "RRULE:FREQ=WEEKLY;COUNT=3")
    )
    do_import(client, content, include_past=True)
    assert len(blocks_between(client)) == 3


def test_importing_the_same_invite_again_updates_it(client, make_folder):
    folder = make_folder()
    first = ics(
        vevent("sync", "Sync", "20261005T100000", "20261005T110000", "RRULE:FREQ=DAILY;COUNT=3")
    )
    do_import(client, first, folder_id=folder["id"])
    blocks = blocks_between(client)
    # Time spent on the first event stays.
    client.patch(f"/api/blocks/{blocks[0]['id']}", json={"kind": "tracked"})

    moved = ics(
        vevent(
            "sync",
            "Sync (moved)",
            "20261005T140000",
            "20261005T150000",
            "RRULE:FREQ=DAILY;COUNT=3",
            "SEQUENCE:1",
        )
    )
    [event] = client.post("/api/import/preview", json={"content": moved}).json()["events"]
    assert event["status"] == "update"

    result = do_import(client, moved, folder_id=folder["id"])
    assert result["updated"] == 1 and result["added"] == 0

    blocks = blocks_between(client)
    assert [(b["kind"], b["starts_at"]) for b in blocks] == [
        ("tracked", "2026-10-05T10:00:00"),
        ("planned", "2026-10-06T14:00:00"),
        ("planned", "2026-10-07T14:00:00"),
    ]


def test_a_cancellation_removes_the_events(client):
    content = ics(
        vevent("party", "Party", "20261005T180000", "20261005T200000", "RRULE:FREQ=DAILY;COUNT=2")
    )
    do_import(client, content)
    cancel = ics(
        vevent("party", "Party", "20261005T180000", "20261005T200000", "STATUS:CANCELLED"),
        method="CANCEL",
    )
    [event] = client.post("/api/import/preview", json={"content": cancel}).json()["events"]
    assert event["status"] == "cancel"

    result = do_import(client, cancel)
    assert result["cancelled"] == 1
    assert blocks_between(client) == []


def test_changed_and_cancelled_instances_of_a_series(client):
    content = ics(
        vevent("s", "Course", "20261005T100000", "20261005T110000", "RRULE:FREQ=DAILY;COUNT=4"),
        vevent(
            "s",
            "Course (room change)",
            "20261006T150000",
            "20261006T160000",
            "RECURRENCE-ID;TZID=Europe/Rome:20261006T100000",
        ),
        vevent(
            "s",
            "Course",
            "20261007T100000",
            "20261007T110000",
            "RECURRENCE-ID;TZID=Europe/Rome:20261007T100000",
            "STATUS:CANCELLED",
        ),
    )
    do_import(client, content)
    blocks = blocks_between(client)
    assert [(b["title"], b["starts_at"]) for b in blocks] == [
        ("Course", "2026-10-05T10:00:00"),
        ("Course (room change)", "2026-10-06T15:00:00"),
        ("Course", "2026-10-08T10:00:00"),
    ]
    assert len({b["recurrence"]["id"] for b in blocks}) == 1

    # A later email moves one instance only.
    update = ics(
        vevent(
            "s",
            "Course",
            "20261008T120000",
            "20261008T130000",
            "RECURRENCE-ID;TZID=Europe/Rome:20261008T100000",
            "SEQUENCE:2",
        ),
        method="REQUEST",
    )
    result = do_import(client, update)
    assert result["updated"] == 1
    assert blocks_between(client)[-1]["starts_at"] == "2026-10-08T12:00:00"


def test_all_day_events_become_tasks_planned_for_the_day(client, make_folder):
    folder = make_folder()
    content = ics(
        vevent(
            "conf",
            "Conference",
            "DTSTART;VALUE=DATE:20261012",
            "DTEND;VALUE=DATE:20261015",
            "LOCATION:Berlin",
        )
    )
    result = do_import(client, content, folder_id=folder["id"])
    assert result["tasks"] == 1
    [task] = client.get("/api/tasks", params={"folder_id": folder["id"]}).json()
    assert task["title"] == "Conference"
    assert task["planned_date"] == "2026-10-12"
    assert task["due_date"] == "2026-10-14"

    # Importing it again doesn't add it twice.
    do_import(client, content, folder_id=folder["id"])
    assert len(client.get("/api/tasks").json()) == 1


def test_only_the_picked_events_are_imported(client):
    content = ics(
        vevent("a", "A", "20261005T100000", "20261005T110000"),
        vevent("b", "B", "20261006T100000", "20261006T110000"),
    )
    do_import(client, content, keys=["b"])
    assert [b["title"] for b in blocks_between(client)] == ["B"]


def test_an_email_with_an_invite(client, make_folder):
    folder = make_folder("Sales")
    invite = ics(
        vevent("demo", "Demo for ACME", "20261008T160000", "20261008T170000"), method="REQUEST"
    )
    encoded = base64.encodebytes(invite.encode()).decode()
    eml = (
        "From: Marco Bianchi <marco@acme.example>\r\n"
        "To: luca@example.com\r\n"
        "Subject: Invitation: Demo for ACME\r\n"
        "Date: Fri, 25 Sep 2026 10:00:00 +0200\r\n"
        "MIME-Version: 1.0\r\n"
        'Content-Type: multipart/mixed; boundary="XX"\r\n\r\n'
        "--XX\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nSee you there.\r\n"
        "--XX\r\nContent-Type: text/calendar; method=REQUEST; charset=utf-8\r\n"
        "Content-Transfer-Encoding: base64\r\n\r\n"
        f"{encoded}\r\n--XX--\r\n"
    )
    preview = client.post("/api/import/preview", json={"content": eml, "filename": "demo.eml"})
    body = preview.json()
    assert body["source"] == "Email: Invitation: Demo for ACME"
    assert [e["title"] for e in body["events"]] == ["Demo for ACME"]
    assert body["draft"] is None

    do_import(client, eml, filename="demo.eml", folder_id=folder["id"])
    [block] = blocks_between(client)
    assert block["folder_id"] == folder["id"]
    assert block["source"] == "Email: Invitation: Demo for ACME"


def test_an_email_without_an_invite_gives_a_draft(client):
    eml = (
        "From: Anna <anna@example.com>\r\nSubject: Re: Fwd: Budget review\r\n"
        "Date: Fri, 25 Sep 2026 10:00:00 +0200\r\n\r\n"
        "Can we meet Thursday at 3pm?\r\n"
    )
    body = client.post("/api/import/preview", json={"content": eml}).json()
    assert body["events"] == []
    draft = body["draft"]
    assert draft["title"] == "Budget review"
    assert "From: Anna <anna@example.com>" in draft["notes"]
    assert "Thursday at 3pm" in draft["notes"]


def test_pasted_text(client):
    invite = ics(vevent("p", "Pasted", "20261005T100000", "20261005T110000"))
    body = client.post(
        "/api/import/preview", json={"content": f"Here it is:\n{invite}\nthanks"}
    ).json()
    assert [e["title"] for e in body["events"]] == ["Pasted"]

    plain = client.post("/api/import/preview", json={"content": "Dentist\nBring the card"}).json()
    assert plain["draft"]["title"] == "Dentist"


def test_folded_lines_are_joined(client):
    content = ics(
        "BEGIN:VEVENT\r\nUID:f\r\nSUMMARY:A very long\r\n  title\r\n"
        "DTSTART:20261005T100000Z\r\nDTEND:20261005T110000Z\r\nEND:VEVENT"
    )
    [event] = client.post("/api/import/preview", json={"content": content}).json()["events"]
    assert event["title"] == "A very long title"


def test_bad_input(client):
    assert client.post("/api/import/preview", json={}).status_code == 422
    broken = client.post(
        "/api/import/preview",
        json={"content": "BEGIN:VCALENDAR\nBEGIN:VEVENT\n", "filename": "x.ics"},
    )
    assert broken.status_code == 422
    assert "Could not read the calendar" in broken.json()["detail"]


@pytest.mark.parametrize(
    "url", ["ftp://example.com/cal.ics", "http://127.0.0.1/cal.ics", "http://10.0.0.5/cal.ics"]
)
def test_links_must_be_public_web_addresses(client, url):
    response = client.post("/api/import/preview", json={"url": url})
    assert response.status_code == 422


def test_links_are_downloaded(client, monkeypatch):
    content = ics(vevent("web", "From the web", "20261005T100000", "20261005T110000"))
    fetched = []
    monkeypatch.setattr(imports, "_fetch", lambda url: fetched.append(url) or content)
    body = client.post(
        "/api/import/preview", json={"url": "webcal://calendar.example.com/team/basic.ics"}
    ).json()
    assert body["source"] == "calendar.example.com · basic.ics"
    assert [e["title"] for e in body["events"]] == ["From the web"]


def test_importing_into_someone_elses_folder_is_a_404(client, client_for, make_user):
    other = client_for(make_user("bob"))
    folder = other.post("/api/folders", json={"name": "Bob's"}).json()
    content = ics(vevent("x", "X", "20261005T100000", "20261005T110000"))
    response = client.post("/api/import", json={"content": content, "folder_id": folder["id"]})
    assert response.status_code == 404


def test_imports_are_per_user(client, client_for, make_user):
    content = ics(vevent("shared-uid", "Mine", "20261005T100000", "20261005T110000"))
    other = client_for(make_user("bob"))
    other.post("/api/import", json={"content": content})
    [event] = client.post("/api/import/preview", json={"content": content}).json()["events"]
    assert event["status"] == "new"


def test_appointments_of_a_folder_and_of_the_inbox(client, make_folder, make_task, make_block):
    folder = make_folder()
    make_block("2026-10-05T09:00", "2026-10-05T10:00", title="Later", folder_id=folder["id"])
    make_block("2026-10-02T09:00", "2026-10-02T10:00", title="Sooner", folder_id=folder["id"])
    make_block("2026-09-01T09:00", "2026-09-01T10:00", title="Done", folder_id=folder["id"])
    make_block("2026-10-02T09:00", "2026-10-02T10:00", title="Inbox one")
    task = make_task(folder_id=folder["id"])
    make_block("2026-10-03T09:00", "2026-10-03T10:00", task_id=task["id"])  # not an appointment

    titles = [
        a["block"]["title"]
        for a in client.get("/api/appointments", params={"folder_id": folder["id"]}).json()
    ]
    assert titles == ["Sooner", "Later", "Done"]
    inbox = client.get("/api/appointments", params={"inbox": True}).json()
    assert [a["block"]["title"] for a in inbox] == ["Inbox one"]


def test_blocks_have_a_location(client, make_block):
    block = make_block("2026-10-05T09:00", "2026-10-05T10:00", title="Call", location=" Zoom ")
    assert block["location"] == "Zoom"
    updated = client.patch(f"/api/blocks/{block['id']}", json={"location": "Room 2"}).json()
    assert updated["location"] == "Room 2"
    assert updated["source"] == ""


def test_an_existing_database_gets_the_new_columns(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE time_blocks (id INTEGER PRIMARY KEY, user_id INTEGER, "
                "kind VARCHAR(20), task_id INTEGER, folder_id INTEGER, title VARCHAR(200), "
                "starts_at DATETIME, ends_at DATETIME, notes TEXT, recurrence_id INTEGER)"
            )
        )
        connection.execute(
            text("INSERT INTO time_blocks (id, title, notes) VALUES (1, 'kept', '')")
        )
    init_db(engine)
    columns = {c["name"] for c in inspect(engine).get_columns("time_blocks")}
    assert {"location", "external_uid", "source"} <= columns
    with engine.connect() as connection:
        assert connection.execute(text("SELECT title FROM time_blocks")).scalar() == "kept"
