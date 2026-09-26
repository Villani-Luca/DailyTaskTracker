"""Calendar blocks (planned time, tracked time, appointments), repeating series and the
task timer."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session, selectinload

from tasktracker.models import (
    BlockKind,
    Frequency,
    Recurrence,
    Task,
    TaskStatus,
    TimeBlock,
    now,
)
from tasktracker.schemas import (
    AppointmentSummary,
    RecurrenceRule,
    SeriesScope,
    TimeBlockCreate,
    TimeBlockRead,
    TimeBlockUpdate,
)
from tasktracker.services.errors import InvalidOperationError, NotFoundError
from tasktracker.services.folders import get_folder
from tasktracker.services.recurrence import occurrences
from tasktracker.services.tasks import get_task, set_status


def _block_query(user_id: int) -> Select[tuple[TimeBlock]]:
    return (
        select(TimeBlock)
        .where(TimeBlock.user_id == user_id)
        .options(
            selectinload(TimeBlock.task).selectinload(Task.folder),
            selectinload(TimeBlock.folder),
            selectinload(TimeBlock.recurrence),
        )
    )


def list_blocks(
    session: Session,
    user_id: int,
    starts_at: datetime,
    ends_at: datetime,
    kind: BlockKind | None = None,
) -> list[TimeBlock]:
    """Blocks overlapping ``[starts_at, ends_at)``, including a running timer."""
    stmt = (
        _block_query(user_id)
        .where(
            TimeBlock.starts_at < ends_at,
            or_(TimeBlock.ends_at.is_(None), TimeBlock.ends_at > starts_at),
        )
        .order_by(TimeBlock.starts_at)
    )
    if kind is not None:
        stmt = stmt.where(TimeBlock.kind == kind)
    return list(session.scalars(stmt))


def get_block(session: Session, user_id: int, block_id: int) -> TimeBlock:
    block = session.scalar(_block_query(user_id).where(TimeBlock.id == block_id))
    if block is None:
        raise NotFoundError("Time block", block_id)
    return block


def list_appointments(
    session: Session, user_id: int, folder_id: int | None = None, inbox: bool = False
) -> list[AppointmentSummary]:
    """The appointments (blocks without a task) of one folder, of the inbox, or all of
    them. A repeating series is one entry. Upcoming ones first, soonest first; then the
    ones that are over, latest first."""
    stmt = _block_query(user_id).where(TimeBlock.task_id.is_(None)).order_by(TimeBlock.starts_at)
    if inbox:
        stmt = stmt.where(TimeBlock.folder_id.is_(None))
    elif folder_id is not None:
        get_folder(session, user_id, folder_id)  # someone else's folder is a 404
        stmt = stmt.where(TimeBlock.folder_id == folder_id)

    groups: dict[Any, list[TimeBlock]] = defaultdict(list)
    for block in session.scalars(stmt):
        key = ("series", block.recurrence_id) if block.recurrence_id else ("block", block.id)
        groups[key].append(block)

    current = now()
    upcoming, past = [], []
    for blocks in groups.values():
        ahead = [b for b in blocks if b.ends_at is None or b.ends_at > current]
        shown = ahead[0] if ahead else blocks[-1]
        summary = AppointmentSummary(
            block=TimeBlockRead.model_validate(shown),
            events=len(blocks),
            upcoming=len(ahead),
            planned_minutes=sum(b.duration_minutes for b in blocks if b.kind is BlockKind.PLANNED),
            tracked_minutes=sum(b.duration_minutes for b in blocks if b.kind is BlockKind.TRACKED),
        )
        (upcoming if ahead else past).append(summary)
    upcoming.sort(key=lambda s: s.block.starts_at)
    past.sort(key=lambda s: s.block.starts_at, reverse=True)
    return upcoming + past


def create_block(session: Session, user_id: int, data: TimeBlockCreate) -> TimeBlock:
    """Add a block. With a recurrence, it is the first event of a new series."""
    block = TimeBlock(user_id=user_id, **data.model_dump(exclude={"task_id", "recurrence"}))
    if data.task_id is not None:
        block.task = get_task(session, user_id, data.task_id)
        block.folder_id = None  # task blocks are colored by the task's folder
    elif data.folder_id is not None:
        get_folder(session, user_id, data.folder_id)

    if block.task is not None and block.kind is BlockKind.PLANNED:
        _follow_plan(block.task, old_day=None, new_day=block.starts_at.date())
    session.add(block)
    if data.recurrence is not None:
        repeat(session, block, data.recurrence)
    session.commit()
    return block


def update_block(
    session: Session,
    user_id: int,
    block_id: int,
    data: TimeBlockUpdate,
    scope: SeriesScope = SeriesScope.THIS,
) -> TimeBlock:
    """Change a block, or a block and the planned events after it in its series.

    ``FOLLOWING`` splits the series: this block starts a new one with the changes (and
    the new recurrence, if given), and the events after it are made again from it.
    Setting the recurrence to None there stops the series after this block.
    """
    if scope is SeriesScope.ALL:
        raise InvalidOperationError("Change this event, or this and the following events")
    block = get_block(session, user_id, block_id)
    changes = data.changes()
    new_rule = "recurrence" in changes
    changes.pop("recurrence", None)
    series = block.recurrence

    if series is not None and scope is SeriesScope.FOLLOWING:
        rule = data.recurrence if new_rule else _rule_of(series)
        _prune_series(session, series, block, following=True)
        _apply_changes(session, user_id, block, changes)
        if rule is not None:
            repeat(session, block, rule)
    else:
        if new_rule and series is not None:
            raise InvalidOperationError(
                "To change how events repeat, apply it to this and the following events"
            )
        _apply_changes(session, user_id, block, changes)
        if data.recurrence is not None:
            repeat(session, block, data.recurrence)
    session.commit()
    return block


def delete_block(
    session: Session, user_id: int, block_id: int, scope: SeriesScope = SeriesScope.THIS
) -> None:
    """Delete a block, or with a scope, planned events of its series too.

    Time already marked as spent is history: series deletes leave it alone.
    """
    block = get_block(session, user_id, block_id)
    series = block.recurrence
    if series is None or scope is SeriesScope.THIS:
        session.delete(block)
        if series is not None:
            drop_if_empty(session, series, gone={block})
    else:
        _prune_series(session, series, block, following=scope is SeriesScope.FOLLOWING)
        session.delete(block)
    session.commit()


def _apply_changes(
    session: Session, user_id: int, block: TimeBlock, changes: dict[str, Any]
) -> None:
    old_day = block.starts_at.date()

    if block.is_running and changes.get("kind", block.kind) is not block.kind:
        raise InvalidOperationError("Stop the timer before changing this block's kind")
    if "task_id" in changes:
        task_id = changes.pop("task_id")
        block.task = get_task(session, user_id, task_id) if task_id is not None else None
    if changes.get("folder_id") is not None:
        get_folder(session, user_id, changes["folder_id"])
    for field, value in changes.items():
        setattr(block, field, value)

    if block.task is not None:
        block.folder_id = None
    if block.ends_at is not None and block.ends_at <= block.starts_at:
        raise InvalidOperationError("A block must end after it starts")
    if block.task is None and not block.title:
        raise InvalidOperationError("An appointment needs a title (or link it to a task)")

    if block.task is not None and block.kind is BlockKind.PLANNED:
        _follow_plan(block.task, old_day=old_day, new_day=block.starts_at.date())


def _follow_plan(task: Task, old_day: date | None, new_day: date) -> None:
    """Placing a task on the calendar plans it for that day.

    The planned date only follows the block when it was unset or matched the block's
    previous day, so a date you picked deliberately is never overwritten.
    """
    if task.planned_date is None or task.planned_date == old_day:
        task.planned_date = new_day


# --- Repeating series ----------------------------------------------------------------


def repeat(
    session: Session,
    block: TimeBlock,
    rule: RecurrenceRule,
    skip_days: Collection[date] = (),
) -> None:
    """Make ``block`` the first event of a new series, and add the events after it
    (except those on a day in ``skip_days``: a series has at most one event a day)."""
    if block.kind is not BlockKind.PLANNED:
        raise InvalidOperationError("Only planned blocks can repeat")
    assert block.ends_at is not None  # only a running timer has no end
    weekdays = []
    if rule.frequency is Frequency.WEEKLY:
        weekdays = sorted(set(rule.weekdays) or {block.starts_at.weekday()})
    starts = occurrences(block.starts_at, rule.frequency, rule.interval, weekdays, rule.until)

    series = Recurrence(
        user_id=block.user_id,
        frequency=rule.frequency,
        interval=rule.interval,
        weekdays=weekdays,
        until=rule.until,
    )
    block.recurrence = series
    duration = block.ends_at - block.starts_at
    for start in starts[1:]:
        if start.date() in skip_days:
            continue
        session.add(
            TimeBlock(
                user_id=block.user_id,
                kind=BlockKind.PLANNED,
                task=block.task,
                folder_id=block.folder_id,
                title=block.title,
                location=block.location,
                notes=block.notes,
                external_uid=block.external_uid,
                source=block.source,
                starts_at=start,
                ends_at=start + duration,
                recurrence=series,
            )
        )


def _rule_of(series: Recurrence) -> RecurrenceRule:
    return RecurrenceRule(
        frequency=series.frequency,
        interval=series.interval,
        weekdays=series.weekdays,
        until=series.until,
    )


def _prune_series(session: Session, series: Recurrence, block: TimeBlock, following: bool) -> None:
    """Take ``block`` out of its series, deleting the series' planned events after it
    (``following``) or all of them. The series then ends before ``block``."""
    gone = {
        other
        for other in series.blocks
        if other is not block
        and other.kind is BlockKind.PLANNED
        and (not following or other.starts_at > block.starts_at)
    }
    for other in gone:
        session.delete(other)
    block.recurrence = None
    if not drop_if_empty(session, series, gone):
        series.until = min(series.until, block.starts_at.date() - timedelta(days=1))


def drop_if_empty(session: Session, series: Recurrence, gone: Collection[TimeBlock]) -> bool:
    if any(b not in gone for b in series.blocks):
        return False
    session.delete(series)
    return True


# --- Timer ---------------------------------------------------------------------------


def get_running_timer(session: Session, user_id: int) -> TimeBlock | None:
    stmt = _block_query(user_id).where(
        TimeBlock.kind == BlockKind.TRACKED, TimeBlock.ends_at.is_(None)
    )
    return session.scalars(stmt).first()


def start_timer(session: Session, user_id: int, task_id: int) -> TimeBlock:
    """Start tracking time on a task. Each user has at most one timer running."""
    task = get_task(session, user_id, task_id)
    running = get_running_timer(session, user_id)
    if running is not None:
        if running.task_id == task_id:
            return running
        running.stop()

    set_status(task, TaskStatus.IN_PROGRESS)
    block = TimeBlock(
        user_id=user_id, kind=BlockKind.TRACKED, task=task, starts_at=now(), ends_at=None
    )
    session.add(block)
    session.commit()
    return block


def stop_timer(session: Session, user_id: int) -> TimeBlock | None:
    running = get_running_timer(session, user_id)
    if running is None:
        return None
    running.stop()
    session.commit()
    return running
