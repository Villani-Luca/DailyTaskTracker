"""Import appointments from .ics files, emails (.eml), pasted text or a calendar link.

Two stateless steps: ``preview`` reads the source and says what an import would do, and
``import_events`` does it for the events the user picked, all into one folder.

- A timed event becomes a planned appointment; a repeating one, a series (see
  calendar.py), so it can be changed or deleted like any other.
- An all-day event becomes a task planned for its day (the calendar's *Tasks* row).
- Every appointment keeps the invite's UID: importing the same invite again replaces its
  planned events, and a cancellation deletes them. Time already spent is never touched.
- An email without an invite gives a draft: the subject and text to start a new
  appointment with.
"""

from __future__ import annotations

import email
import hashlib
import html
import ipaddress
import re
import socket
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from email import policy
from email.message import EmailMessage
from itertools import islice
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from sqlalchemy import select
from sqlalchemy.orm import Session

from tasktracker.models import BlockKind, Frequency, Task, TimeBlock, now
from tasktracker.schemas import (
    AppointmentDraft,
    ImportEvent,
    ImportPreview,
    ImportRequest,
    ImportResult,
    ImportSource,
    ImportStatus,
    RecurrenceRule,
)
from tasktracker.services import calendar, ical
from tasktracker.services.errors import InvalidOperationError
from tasktracker.services.folders import get_folder
from tasktracker.services.recurrence import MAX_EVENTS, occurrence_days

HORIZON_DAYS = 365  # a series that repeats forever is imported for a year
MAX_NOTES = 10_000
MAX_ATTENDEES = 30
FETCH_TIMEOUT = 10  # seconds
MAX_FETCH_BYTES = 5_000_000
WEEKDAY_CODES = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
_EMAIL_HEADER = re.compile(
    r"^(from|to|subject|date|received|return-path|message-id|mime-version|delivered-to):",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass
class _Source:
    name: str
    calendars: list[ical.Calendar] = field(default_factory=list)
    draft: AppointmentDraft | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class _Item:
    """One entry of the preview: an event with the changed instances of its series, or
    a lone changed (or cancelled) instance of a series imported before."""

    key: str
    event: ical.Event
    overrides: list[ical.Event] = field(default_factory=list)

    @property
    def uid(self) -> str:
        return self.event.uid

    @property
    def is_instance(self) -> bool:
        return self.event.recurrence_id is not None


@dataclass
class _Plan:
    """The events an item adds: when they start, and the series rule that makes them."""

    starts: list[datetime]
    rule: RecurrenceRule | None
    skip_days: set[date]
    overrides: list[ical.Event]  # changed instances, added as events of their own
    past: int
    warnings: list[str]

    @property
    def count(self) -> int:
        return len(self.starts) + len(self.overrides)


# --- Reading the source --------------------------------------------------------------


def read_source(source: ImportSource) -> _Source:
    if source.url:
        name = _link_name(source.url)
        return _from_text(_fetch(source.url), kind="ics", name=name)
    content = source.content or ""
    filename = source.filename
    lower = filename.lower()
    if lower.endswith((".ics", ".ical", ".icalendar", ".vcs")):
        kind = "ics"
    elif lower.endswith(".eml"):
        kind = "email"
    elif content.lstrip().upper().startswith("BEGIN:VCALENDAR"):
        kind = "ics"
    elif _looks_like_email(content):
        kind = "email"
    else:
        kind = "text"
    return _from_text(content, kind=kind, name=filename or "Pasted text")


def _from_text(text: str, kind: str, name: str) -> _Source:
    if kind == "email":
        return _from_email(text, name)
    if kind == "text":
        # An invite copied out of something else: take the calendar part.
        match = re.search(r"BEGIN:VCALENDAR.*?END:VCALENDAR", text, re.DOTALL | re.IGNORECASE)
        if match is None:
            return _Source(name=name, draft=_text_draft(text))
        text = match.group(0)
    return _Source(name=name, calendars=_calendars(text))


def _calendars(text: str) -> list[ical.Calendar]:
    try:
        return ical.read_calendars(text)
    except ical.ICalError as exc:
        raise InvalidOperationError(f"Could not read the calendar: {exc}") from None


def _looks_like_email(text: str) -> bool:
    head = re.split(r"\r?\n\r?\n", text.lstrip(), maxsplit=1)[0]
    return len(_EMAIL_HEADER.findall(head)) >= 2


def _from_email(text: str, name: str) -> _Source:
    message = email.message_from_string(text, policy=policy.default)
    assert isinstance(message, EmailMessage)
    subject = " ".join(str(message["subject"] or "").split())
    sender = str(message["from"] or "")
    source = _Source(name=f"Email: {subject}" if subject else name)

    for part in message.walk():
        if part.is_multipart():
            continue
        filename = (part.get_filename() or "").lower()
        if part.get_content_type() in ("text/calendar", "application/ics") or filename.endswith(
            (".ics", ".vcs")
        ):
            payload = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            try:
                source.calendars += ical.read_calendars(payload.decode(charset, "replace"))
            except (ical.ICalError, LookupError) as exc:
                source.warnings.append(f"An invite in the email could not be read: {exc}")

    if not source.calendars:
        body = _email_text(message)
        header = "\n".join(
            line
            for line in (
                f"From: {sender}" if sender else "",
                f"Date: {message['date']}" if message["date"] else "",
                f"Subject: {subject}" if subject else "",
            )
            if line
        )
        source.draft = AppointmentDraft(
            title=_clip(_clean_subject(subject) or "Appointment", 200),
            notes=_clip("\n\n".join(p for p in (header, body) if p), MAX_NOTES),
            source=source.name,
        )
    return source


def _email_text(message: EmailMessage) -> str:
    part = message.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        text = part.get_content()
    except (LookupError, ValueError):
        return ""
    if part.get_content_type() == "text/html":
        text = re.sub(r"(?is)<(script|style).*?</\1>", "", text)
        text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", text)
        text = html.unescape(re.sub(r"<[^>]+>", "", text))
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _clean_subject(subject: str) -> str:
    """Drop reply and forward prefixes: "Re: Fwd: Kickoff" -> "Kickoff"."""
    return re.sub(r"^(?:\s*(?:re|fw|fwd|r|i|tr|wg|aw)\s*:\s*)+", "", subject, flags=re.I).strip()


def _text_draft(text: str) -> AppointmentDraft:
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if not lines:
        raise InvalidOperationError("There is nothing to import")
    return AppointmentDraft(
        title=_clip(lines[0], 200), notes=_clip(text.strip(), MAX_NOTES), source="Pasted text"
    )


# --- Downloading a calendar link -----------------------------------------------------


class _SafeRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _check_url(url: str) -> None:
    """Only public http(s) addresses: the server must not be a way into its own network."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise InvalidOperationError("Use an https://, http:// or webcal:// link")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 443, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        raise InvalidOperationError(f"Could not find the server {parts.hostname}") from None
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            raise InvalidOperationError("Links to private network addresses are not allowed")


def _normalize_link(url: str) -> str:
    if url.lower().startswith("webcal://"):
        return "https://" + url[len("webcal://") :]
    return url


def _link_name(url: str) -> str:
    parts = urlsplit(_normalize_link(url))
    last = parts.path.rstrip("/").rsplit("/", 1)[-1]
    return _clip(f"{parts.hostname or 'link'}{f' · {last}' if last else ''}", 300)


def _fetch(url: str) -> str:
    url = _normalize_link(url)
    _check_url(url)
    request = Request(url, headers={"User-Agent": "DailyTaskTracker", "Accept": "text/calendar"})
    opener = build_opener(_SafeRedirects)
    try:
        with opener.open(request, timeout=FETCH_TIMEOUT) as response:
            body = response.read(MAX_FETCH_BYTES + 1)
            charset = response.headers.get_content_charset() or "utf-8"
    except HTTPError as exc:
        raise InvalidOperationError(f"Could not download the calendar: HTTP {exc.code}") from None
    except (URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        raise InvalidOperationError(f"Could not download the calendar: {reason}") from None
    if len(body) > MAX_FETCH_BYTES:
        raise InvalidOperationError("That calendar is too big (more than 5 MB)")
    return body.decode(charset, "replace")


# --- Events and what importing them does ---------------------------------------------


def _items(calendars: list[ical.Calendar]) -> list[_Item]:
    """Events by UID; for the same event (or instance) sent twice, the latest version."""
    latest: dict[tuple[str, datetime | None], ical.Event] = {}
    for cal in calendars:
        for event in cal.events:
            if not event.uid:
                digest = hashlib.sha1(f"{event.title}|{event.starts_at.isoformat()}".encode())
                event.uid = f"generated-{digest.hexdigest()[:20]}"
            if cal.method == "CANCEL":
                event.cancelled = True
            key = (event.uid, event.recurrence_id)
            if key not in latest or event.sequence >= latest[key].sequence:
                latest[key] = event

    masters = {uid for uid, rid in latest if rid is None}
    items = []
    for (uid, rid), event in latest.items():
        if rid is None:
            overrides = [e for (u, r), e in latest.items() if u == uid and r is not None]
            items.append(_Item(key=uid, event=event, overrides=overrides))
        elif uid not in masters:
            items.append(_Item(key=f"{uid}@{rid.isoformat()}", event=event))
    items.sort(key=lambda i: i.event.starts_at)
    return items


def _series_rule(
    rrule: dict[str, str], first: datetime, warnings: list[str]
) -> tuple[Frequency, int, list[int]] | None:
    """The app's repeat rule for an RRULE: daily, weekly on some days, or monthly on the
    first event's day. None (with a warning) for anything else."""
    frequency = rrule.get("FREQ", "")
    byday = [d for d in rrule.get("BYDAY", "").split(",") if d]
    monthday, month = rrule.get("BYMONTHDAY"), rrule.get("BYMONTH")
    extra = set(rrule) - {"FREQ", "INTERVAL", "UNTIL", "COUNT", "WKST", "BYDAY"}
    extra -= {"BYMONTHDAY", "BYMONTH"}
    try:
        interval = max(1, int(rrule.get("INTERVAL") or 1))
    except ValueError:
        interval = 0
    plain_days = all(d in WEEKDAY_CODES for d in byday)
    weekdays = sorted({WEEKDAY_CODES[d] for d in byday}) if plain_days else []

    if interval and not extra and plain_days:
        if frequency == "DAILY" and not monthday and not month:
            if not weekdays:
                return Frequency.DAILY, interval, []
            if interval == 1:  # "every weekday"
                return Frequency.WEEKLY, 1, weekdays
        elif frequency == "WEEKLY" and not monthday and not month:
            return Frequency.WEEKLY, interval, weekdays or [first.weekday()]
        elif frequency == "MONTHLY" and not byday and not month:
            if monthday in (None, str(first.day)):
                return Frequency.MONTHLY, interval, []
        elif frequency == "YEARLY" and not byday and interval * 12 <= 99:
            if monthday in (None, str(first.day)) and month in (None, str(first.month)):
                return Frequency.MONTHLY, interval * 12, []

    rule_text = ";".join(f"{k}={v}" for k, v in rrule.items())
    warnings.append(f"This repeat can't be imported as a series ({rule_text}): only one event")
    return None


def _plan(item: _Item, include_past: bool, current: datetime, keep: set[date]) -> _Plan:
    """What importing ``item`` adds. ``keep``: days that already have spent time for
    this event, so they don't get a planned event again."""
    event = item.event
    duration = event.ends_at - event.starts_at
    warnings = list(event.warnings)
    skip = {e.date() for e in event.exdates} | {
        o.recurrence_id.date() for o in item.overrides if o.recurrence_id
    }
    skip |= keep

    def over(start: datetime) -> bool:
        return start + duration <= current

    rule = None
    mapped = None
    if event.rrule is not None and not item.is_instance:
        mapped = _series_rule(event.rrule, event.starts_at, warnings)

    if mapped is None:
        candidates = [event.starts_at]
    else:
        frequency, interval, weekdays = mapped
        last_start = ical.rrule_until(event.rrule or {}, warnings)
        until = last_start.date() if last_start else None
        count = None
        if "COUNT" in (event.rrule or {}):
            try:
                count = max(1, int(event.rrule["COUNT"]))  # type: ignore[index]
            except ValueError:
                count = 1
        if until is None and count is None:
            until = max(event.starts_at.date(), current.date()) + timedelta(days=HORIZON_DAYS)
            warnings.append(f"Repeats with no end: events are added up to {until:%d %b %Y}")
        elif until is None:
            until = event.starts_at.date() + timedelta(days=366 * 50)
        days = occurrence_days(event.starts_at.date(), frequency, interval, weekdays, until)
        # Enough to reach today from an old series, not unbounded.
        days = islice(days, count if count is not None else 20_000)
        candidates = [datetime.combine(d, event.starts_at.time()) for d in days]
        if last_start is not None:
            candidates = [s for s in candidates if s <= last_start] or [event.starts_at]
        if len(candidates) > 1:
            rule = (frequency, interval, weekdays)

    past = 0
    if not include_past:
        past = sum(1 for s in candidates if over(s) and s.date() not in skip)
        candidates = [s for s in candidates if not over(s)]
    while candidates and candidates[0].date() in skip:
        candidates.pop(0)  # a series starts on an event that happens
    if len(candidates) > MAX_EVENTS:
        candidates = candidates[:MAX_EVENTS]
        warnings.append(
            f"Only the first {MAX_EVENTS} events are added (until {candidates[-1]:%d %b %Y})"
        )
    starts = [s for s in candidates if s.date() not in skip]

    series_rule = None
    if rule is not None and len(starts) > 1:
        frequency, interval, weekdays = rule
        series_rule = RecurrenceRule(
            frequency=frequency,
            interval=interval,
            weekdays=weekdays if frequency is Frequency.WEEKLY else [],
            until=candidates[-1].date(),
        )

    overrides = [
        o for o in item.overrides if not o.cancelled and (include_past or o.ends_at > current)
    ]
    if not include_past:
        past += sum(1 for o in item.overrides if not o.cancelled and o.ends_at <= current)

    if event.all_day and (series_rule is not None or overrides):
        day = starts[0] if starts else event.starts_at
        warnings.append(f"All-day and repeating: only the day {day:%d %b %Y} is added, as a task")
        starts, series_rule, overrides = starts[:1], None, []

    return _Plan(
        starts=starts,
        rule=series_rule,
        skip_days=skip,
        overrides=overrides,
        past=past,
        warnings=warnings,
    )


# --- Preview and import --------------------------------------------------------------


def preview(session: Session, user_id: int, source: ImportSource) -> ImportPreview:
    read = read_source(source)
    items = _items(read.calendars)
    current = now()
    existing = _existing_blocks(session, user_id, [i.uid for i in items])
    events = []
    for item in items:
        blocks = existing.get(item.uid, [])
        plan = _plan(item, include_past=False, current=current, keep=_spent_days(blocks))
        events.append(_preview_event(session, user_id, item, plan, blocks))
    warnings = list(read.warnings)
    if not events and read.draft is None:
        warnings.append("No events found")
    return ImportPreview(source=read.name, events=events, draft=read.draft, warnings=warnings)


def _preview_event(
    session: Session, user_id: int, item: _Item, plan: _Plan, blocks: list[TimeBlock]
) -> ImportEvent:
    event = item.event
    if event.cancelled:
        status = ImportStatus.CANCEL
    elif _matching(item, blocks) or (
        event.all_day and _existing_task(session, user_id, event) is not None
    ):
        status = ImportStatus.UPDATE
    else:
        status = ImportStatus.NEW
    warnings = list(plan.warnings)
    if status is ImportStatus.CANCEL and not _matching(item, blocks):
        warnings = ["Not in your calendar: there is nothing to cancel"]
    return ImportEvent(
        key=item.key,
        status=status,
        title=_title(event),
        starts_at=event.starts_at,
        ends_at=event.ends_at,
        all_day=event.all_day,
        location=event.location,
        organizer=event.organizer,
        recurrence=plan.rule,
        events=0 if event.cancelled else plan.count,
        past_events=0 if event.cancelled else plan.past,
        warnings=warnings,
    )


def import_events(session: Session, user_id: int, data: ImportRequest) -> ImportResult:
    if data.folder_id is not None:
        get_folder(session, user_id, data.folder_id)
    read = read_source(data)
    items = _items(read.calendars)
    if data.keys is not None:
        wanted = set(data.keys)
        items = [i for i in items if i.key in wanted]
    current = now()
    existing = _existing_blocks(session, user_id, [i.uid for i in items])
    result = ImportResult(
        added=0, updated=0, cancelled=0, blocks=0, tasks=0, warnings=list(read.warnings)
    )

    for item in items:
        blocks = existing.get(item.uid, [])
        event = item.event
        if event.cancelled:
            if _delete_planned(session, _matching(item, blocks)):
                result.cancelled += 1
            continue
        plan = _plan(item, data.include_past, current, keep=_spent_days(blocks))
        result.warnings += [f"{_title(event)}: {w}" for w in plan.warnings]
        if event.all_day:
            if plan.starts:
                updated = _import_task(session, user_id, event, plan.starts[0], data, read.name)
                result.tasks += 1
                result.updated += updated
                result.added += not updated
            continue
        if item.is_instance:
            found = bool(_matching(item, blocks))
            created = _import_instance(session, user_id, item, blocks, data, read.name, current)
            result.blocks += created
            result.updated += found
            result.added += bool(created) and not found
            continue

        replaced = _delete_planned(session, blocks)
        created = _import_series(session, user_id, item, plan, data.folder_id, read.name)
        result.blocks += created
        if replaced:
            result.updated += 1
        elif created:
            result.added += 1
    session.commit()
    return result


def _import_series(
    session: Session,
    user_id: int,
    item: _Item,
    plan: _Plan,
    folder_id: int | None,
    source_name: str,
) -> int:
    event = item.event
    duration = event.ends_at - event.starts_at
    created = 0
    first = None
    if plan.starts:
        first = _block(user_id, event, plan.starts[0], plan.starts[0] + duration, folder_id)
        first.source = _clip(source_name, 300)
        session.add(first)
        created = 1
        if plan.rule is not None:
            calendar.repeat(session, first, plan.rule, skip_days=plan.skip_days)
            session.flush()
            created = len(first.recurrence.blocks) if first.recurrence else 1
    for override in plan.overrides:
        block = _block(user_id, override, override.starts_at, override.ends_at, folder_id)
        block.external_uid = _clip(event.uid, 255)
        block.source = _clip(source_name, 300)
        if first is not None and first.recurrence is not None:
            block.recurrence = first.recurrence
        session.add(block)
        created += 1
    return created


def _import_instance(
    session: Session,
    user_id: int,
    item: _Item,
    blocks: list[TimeBlock],
    data: ImportRequest,
    source_name: str,
    current: datetime,
) -> int:
    """A changed instance of a series: move the event it changes, or add it."""
    event = item.event
    matching = [b for b in _matching(item, blocks) if b.kind is BlockKind.PLANNED]
    if matching:
        block = matching[0]
        block.starts_at, block.ends_at = event.starts_at, event.ends_at
        block.title = _title(event)
        block.location = _clip(event.location, 500)
        block.notes = _notes(event)
        return 0
    if not data.include_past and event.ends_at <= current:
        return 0
    block = _block(user_id, event, event.starts_at, event.ends_at, data.folder_id)
    block.source = _clip(source_name, 300)
    session.add(block)
    return 1


def _import_task(
    session: Session,
    user_id: int,
    event: ical.Event,
    day: datetime,
    data: ImportRequest,
    source_name: str,
) -> bool:
    """An all-day event as a task planned for its day; True when it was there already."""
    last_day = (day + (event.ends_at - event.starts_at) - timedelta(days=1)).date()
    description = "\n\n".join(p for p in (_notes(event), f"Imported from {source_name}") if p)
    task = _existing_task(session, user_id, event, day.date())
    found = task is not None
    if task is None:
        task = Task(user_id=user_id, title=_title(event), planned_date=day.date())
        session.add(task)
    task.folder_id = data.folder_id
    task.description = _clip(description, MAX_NOTES)
    task.due_date = last_day if last_day > day.date() else None
    return found


# --- Helpers -------------------------------------------------------------------------


def _block(
    user_id: int, event: ical.Event, starts_at: datetime, ends_at: datetime, folder_id: int | None
) -> TimeBlock:
    return TimeBlock(
        user_id=user_id,
        kind=BlockKind.PLANNED,
        folder_id=folder_id,
        title=_title(event),
        starts_at=starts_at,
        ends_at=ends_at,
        location=_clip(event.location, 500),
        notes=_notes(event),
        external_uid=_clip(event.uid, 255),
    )


def _existing_blocks(session: Session, user_id: int, uids: list[str]) -> dict[str, list[TimeBlock]]:
    found: dict[str, list[TimeBlock]] = {}
    wanted = sorted({_clip(u, 255) for u in uids})
    for start in range(0, len(wanted), 500):
        stmt = select(TimeBlock).where(
            TimeBlock.user_id == user_id, TimeBlock.external_uid.in_(wanted[start : start + 500])
        )
        for block in session.scalars(stmt):
            found.setdefault(block.external_uid or "", []).append(block)
    return {uid: found.get(_clip(uid, 255), []) for uid in uids}


def _matching(item: _Item, blocks: list[TimeBlock]) -> list[TimeBlock]:
    """The blocks an item replaces: all of the event's, or the one of a lone instance."""
    rid = item.event.recurrence_id
    if rid is None:
        return blocks
    return [b for b in blocks if b.starts_at.date() == rid.date()]


def _spent_days(blocks: list[TimeBlock]) -> set[date]:
    return {b.starts_at.date() for b in blocks if b.kind is BlockKind.TRACKED}


def _delete_planned(session: Session, blocks: list[TimeBlock]) -> bool:
    """Delete the planned ones (time spent is history), and series left empty."""
    gone = [b for b in blocks if b.kind is BlockKind.PLANNED]
    series = {b.recurrence for b in gone if b.recurrence is not None}
    for block in gone:
        session.delete(block)
    for s in series:
        calendar.drop_if_empty(session, s, gone=set(gone))
    return bool(gone)


def _existing_task(
    session: Session, user_id: int, event: ical.Event, day: date | None = None
) -> Task | None:
    stmt = select(Task).where(
        Task.user_id == user_id,
        Task.title == _title(event),
        Task.planned_date == (day or event.starts_at.date()),
    )
    return session.scalars(stmt).first()


def _title(event: ical.Event) -> str:
    return _clip(" ".join(event.title.split()), 200) or "(No title)"


def _notes(event: ical.Event) -> str:
    details = []
    if event.organizer:
        details.append(f"Organizer: {event.organizer}")
    if event.attendees:
        shown = ", ".join(event.attendees[:MAX_ATTENDEES])
        more = len(event.attendees) - MAX_ATTENDEES
        details.append(f"Attendees: {shown}{f' and {more} more' if more > 0 else ''}")
    if event.url:
        details.append(f"Link: {event.url}")
    parts = [event.description.strip(), "\n".join(details)]
    return _clip("\n\n".join(p for p in parts if p), MAX_NOTES)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
