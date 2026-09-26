"""When the events of a repeating series happen."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import suppress
from datetime import date, datetime, timedelta

from tasktracker.models import Frequency
from tasktracker.services.errors import InvalidOperationError

MAX_EVENTS = 500


def occurrences(
    first: datetime, frequency: Frequency, interval: int, weekdays: list[int], until: date
) -> list[datetime]:
    """Start times of every event of a series, ``first`` included, up to ``until``.

    The first event always counts, even on a day the rule wouldn't pick. The others
    fall on the days the rule picks, at the first event's time of day.
    """
    if until < first.date():
        raise InvalidOperationError("A repeating event must end on or after its first day")
    starts = [first]
    for day in _days_after(first.date(), frequency, interval, weekdays, until):
        if len(starts) == MAX_EVENTS:
            raise InvalidOperationError(
                f"That repeats more than {MAX_EVENTS} times: pick an earlier end date"
            )
        starts.append(datetime.combine(day, first.time()))
    return starts


def _days_after(
    first: date, frequency: Frequency, interval: int, weekdays: list[int], until: date
) -> Iterator[date]:
    if frequency is Frequency.DAILY:
        day = first + timedelta(days=interval)
        while day <= until:
            yield day
            day += timedelta(days=interval)

    elif frequency is Frequency.WEEKLY:
        week = first - timedelta(days=first.weekday())  # its Monday
        while week <= until:
            for weekday in sorted(set(weekdays)):
                day = week + timedelta(days=weekday)
                if first < day <= until:
                    yield day
            week += timedelta(weeks=interval)

    else:
        months = interval
        while True:
            year, month = divmod(first.month - 1 + months, 12)
            if date(first.year + year, month + 1, 1) > until:
                return
            with suppress(ValueError):  # no such day that month, e.g. 31 April
                day = date(first.year + year, month + 1, first.day)
                if day <= until:
                    yield day
            months += interval
