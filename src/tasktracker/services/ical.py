"""Read iCalendar data (RFC 5545): the events of an .ics file or of an email invite.

A small reader for what calendar apps actually send: events with their times and time
zones, repeat rules, exceptions, changed instances and cancellations. Times come out
as naive local time, like everything else in the app (see models.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tasktracker.config import local_timezone

# Outlook and Exchange name time zones the Windows way.
WINDOWS_ZONES = {
    "W. Europe Standard Time": "Europe/Berlin",
    "Romance Standard Time": "Europe/Paris",
    "Central Europe Standard Time": "Europe/Budapest",
    "Central European Standard Time": "Europe/Warsaw",
    "GMT Standard Time": "Europe/London",
    "Greenwich Standard Time": "Atlantic/Reykjavik",
    "E. Europe Standard Time": "Europe/Chisinau",
    "FLE Standard Time": "Europe/Kyiv",
    "GTB Standard Time": "Europe/Bucharest",
    "Russian Standard Time": "Europe/Moscow",
    "Turkey Standard Time": "Europe/Istanbul",
    "Israel Standard Time": "Asia/Jerusalem",
    "South Africa Standard Time": "Africa/Johannesburg",
    "Arabian Standard Time": "Asia/Dubai",
    "India Standard Time": "Asia/Kolkata",
    "China Standard Time": "Asia/Shanghai",
    "Singapore Standard Time": "Asia/Singapore",
    "Tokyo Standard Time": "Asia/Tokyo",
    "AUS Eastern Standard Time": "Australia/Sydney",
    "New Zealand Standard Time": "Pacific/Auckland",
    "Eastern Standard Time": "America/New_York",
    "Central Standard Time": "America/Chicago",
    "Mountain Standard Time": "America/Denver",
    "US Mountain Standard Time": "America/Phoenix",
    "Pacific Standard Time": "America/Los_Angeles",
    "Alaskan Standard Time": "America/Anchorage",
    "Hawaiian Standard Time": "Pacific/Honolulu",
    "Atlantic Standard Time": "America/Halifax",
    "E. South America Standard Time": "America/Sao_Paulo",
    "UTC": "UTC",
    "Coordinated Universal Time": "UTC",
}

_DURATION = re.compile(
    r"^(?P<sign>[+-])?P(?:(?P<weeks>\d+)W)?(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


class ICalError(ValueError):
    pass


@dataclass
class Property:
    name: str
    params: dict[str, str]
    value: str


@dataclass
class Component:
    name: str
    props: list[Property] = field(default_factory=list)
    children: list[Component] = field(default_factory=list)

    def get(self, name: str) -> Property | None:
        return next((p for p in self.props if p.name == name), None)

    def all(self, name: str) -> list[Property]:
        return [p for p in self.props if p.name == name]

    def text(self, name: str) -> str:
        prop = self.get(name)
        return unescape(prop.value).strip() if prop else ""


@dataclass
class Event:
    uid: str
    title: str
    starts_at: datetime  # naive local time; midnight for all-day events
    ends_at: datetime
    all_day: bool
    description: str = ""
    location: str = ""
    organizer: str = ""
    attendees: list[str] = field(default_factory=list)
    url: str = ""
    rrule: dict[str, str] | None = None
    exdates: list[datetime] = field(default_factory=list)
    recurrence_id: datetime | None = None  # set on a changed instance of a series
    cancelled: bool = False
    sequence: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass
class Calendar:
    method: str  # "REQUEST", "CANCEL", "PUBLISH"... ("" when not given)
    events: list[Event]


# --- Content lines -------------------------------------------------------------------


def unfold(text: str) -> list[str]:
    """Split into content lines, joining the continuation lines of long ones."""
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif raw.strip():
            lines.append(raw)
    return lines


def parse_line(line: str) -> Property:
    """``NAME;PARAM=value;PARAM="quoted":value`` -> Property."""
    in_quotes = False
    parts: list[str] = []
    start = 0
    for i, char in enumerate(line):
        if char == '"':
            in_quotes = not in_quotes
        elif char in ";:" and not in_quotes:
            parts.append(line[start:i])
            start = i + 1
            if char == ":":
                break
    else:
        raise ICalError(f"Not an iCalendar line: {line[:60]!r}")
    name, *raw_params = parts
    params = {}
    for raw in raw_params:
        key, _, value = raw.partition("=")
        params[key.strip().upper()] = value.strip().strip('"')
    return Property(name.strip().upper(), params, line[start:])


def unescape(value: str) -> str:
    return re.sub(r"\\([\\;,nN])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), value)


def parse_components(text: str) -> list[Component]:
    """The top-level components (normally VCALENDARs) of iCalendar text."""
    roots: list[Component] = []
    stack: list[Component] = []
    for line in unfold(text):
        prop = parse_line(line)
        if prop.name == "BEGIN":
            component = Component(prop.value.strip().upper())
            (stack[-1].children if stack else roots).append(component)
            stack.append(component)
        elif prop.name == "END":
            if not stack or stack[-1].name != prop.value.strip().upper():
                raise ICalError(f"Unexpected END:{prop.value}")
            stack.pop()
        elif stack:
            stack[-1].props.append(prop)
    if stack:
        raise ICalError(f"BEGIN:{stack[-1].name} is never closed")
    return roots


# --- Values --------------------------------------------------------------------------


def zone_for(tzid: str) -> ZoneInfo | None:
    """The time zone a TZID names: an Olson name, a Windows name, or a path ending in
    one ("/mozilla.org/20050126_1/Europe/Rome")."""
    tzid = tzid.strip()
    candidates = [tzid, WINDOWS_ZONES.get(tzid, "")]
    segments = tzid.strip("/").split("/")
    candidates += ["/".join(segments[-n:]) for n in (3, 2, 1) if len(segments) >= n]
    if "utc" in tzid.lower():  # "tzone://Microsoft/Utc"
        candidates.append("UTC")
    for name in candidates:
        if not name:
            continue
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            continue
    return None


def _local(value: datetime) -> datetime:
    return value.astimezone(local_timezone()).replace(tzinfo=None)


def parse_time(value: str, params: dict[str, str], warnings: list[str]) -> datetime | date:
    """A DATE or DATE-TIME value: a date, or a naive local datetime."""
    value = value.strip()
    try:
        if params.get("VALUE", "").upper() == "DATE" or len(value) == 8:
            return datetime.strptime(value[:8], "%Y%m%d").date()
        utc = value.endswith("Z")
        parsed = datetime.strptime(value.rstrip("Z")[:15], "%Y%m%dT%H%M%S")
    except ValueError:
        raise ICalError(f"Not a date or time: {value!r}") from None
    if utc:
        return _local(parsed.replace(tzinfo=UTC))
    tzid = params.get("TZID")
    if tzid:
        zone = zone_for(tzid)
        if zone is not None:
            return _local(parsed.replace(tzinfo=zone))
        message = f"Unknown time zone {tzid!r}: times are taken as your local time"
        if message not in warnings:
            warnings.append(message)
    return parsed  # "floating" time: the same wall-clock time everywhere


def parse_duration(value: str) -> timedelta:
    match = _DURATION.match(value.strip())
    if not match:
        raise ICalError(f"Not a duration: {value!r}")
    parts = {k: int(v) for k, v in match.groupdict().items() if v and k != "sign"}
    delta = timedelta(**parts)
    return -delta if match.group("sign") == "-" else delta


def parse_rrule(value: str) -> dict[str, str]:
    rule = {}
    for part in value.strip().split(";"):
        key, _, val = part.partition("=")
        if key:
            rule[key.strip().upper()] = val.strip().upper() if key.upper() != "UNTIL" else val
    return rule


def _as_datetime(value: datetime | date) -> datetime:
    return value if isinstance(value, datetime) else datetime.combine(value, datetime.min.time())


def _person(prop: Property) -> str:
    """``CN=Anna Rossi:mailto:anna@example.com`` -> "Anna Rossi <anna@example.com>"."""
    email = re.sub(r"^mailto:", "", prop.value.strip(), flags=re.IGNORECASE)
    name = prop.params.get("CN", "").strip()
    if name and email and name.lower() != email.lower():
        return f"{name} <{email}>"
    return name or email


# --- Events --------------------------------------------------------------------------


def read_calendars(text: str) -> list[Calendar]:
    """Every VCALENDAR in ``text``, with its events."""
    calendars = [c for c in parse_components(text) if c.name == "VCALENDAR"]
    if not calendars:
        raise ICalError("No calendar found (expected BEGIN:VCALENDAR)")
    return [
        Calendar(
            method=cal.text("METHOD").upper(),
            events=[_event(c) for c in cal.children if c.name == "VEVENT"],
        )
        for cal in calendars
    ]


def _event(component: Component) -> Event:
    warnings: list[str] = []
    start_prop = component.get("DTSTART")
    if start_prop is None:
        raise ICalError(f"The event {component.text('SUMMARY')!r} has no start time")
    start = parse_time(start_prop.value, start_prop.params, warnings)
    all_day = not isinstance(start, datetime)

    end_prop = component.get("DTEND") or component.get("DUE")
    duration_prop = component.get("DURATION")
    if end_prop is not None:
        end = _as_datetime(parse_time(end_prop.value, end_prop.params, warnings))
    elif duration_prop is not None:
        end = _as_datetime(start) + parse_duration(duration_prop.value)
    else:
        # RFC 5545: a day for a date, no length at all for a time. Give it an hour.
        end = _as_datetime(start) + (timedelta(days=1) if all_day else timedelta(hours=1))
    starts_at = _as_datetime(start)
    if end <= starts_at:
        end = starts_at + (timedelta(days=1) if all_day else timedelta(hours=1))

    exdates = []
    for prop in component.all("EXDATE"):
        for value in prop.value.split(","):
            if value.strip():
                exdates.append(_as_datetime(parse_time(value, prop.params, warnings)))

    recurrence_id = None
    if (prop := component.get("RECURRENCE-ID")) is not None:
        recurrence_id = _as_datetime(parse_time(prop.value, prop.params, warnings))

    rrule = None
    if (prop := component.get("RRULE")) is not None:
        rrule = parse_rrule(prop.value)
    if len(component.all("RRULE")) > 1 or component.get("RDATE") is not None:
        warnings.append("Extra repeat dates (RDATE, or a second RRULE) are not imported")

    try:
        sequence = int(component.text("SEQUENCE") or 0)
    except ValueError:
        sequence = 0
    organizer = component.get("ORGANIZER")

    return Event(
        uid=component.text("UID"),
        title=component.text("SUMMARY"),
        starts_at=starts_at,
        ends_at=end,
        all_day=all_day,
        description=component.text("DESCRIPTION"),
        location=component.text("LOCATION"),
        organizer=_person(organizer) if organizer else "",
        attendees=[_person(p) for p in component.all("ATTENDEE")],
        url=component.text("URL"),
        rrule=rrule,
        exdates=exdates,
        recurrence_id=recurrence_id,
        cancelled=component.text("STATUS").upper() == "CANCELLED",
        sequence=sequence,
        warnings=warnings,
    )


def rrule_until(rule: dict[str, str], warnings: list[str]) -> datetime | None:
    """The last moment an event of a repeat rule can start (UNTIL), in local time. A
    date means that whole day."""
    if "UNTIL" not in rule:
        return None
    value = parse_time(rule["UNTIL"], {}, warnings)
    if isinstance(value, datetime):
        return value
    return datetime.combine(value, datetime.max.time())
