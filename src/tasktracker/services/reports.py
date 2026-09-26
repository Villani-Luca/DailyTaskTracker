"""Read-only views: the daily overview, per-folder statistics and time reports."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Hashable, Iterator
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tasktracker.models import INBOX_COLOR, BlockKind, Task, TaskStatus, TimeBlock, now
from tasktracker.schemas import (
    DayPlan,
    DayTime,
    FolderStats,
    FolderTime,
    Overview,
    StatusCount,
    TaskRead,
    TaskTime,
    TimeBlockRead,
    TimeReport,
)
from tasktracker.services import calendar, tasks
from tasktracker.services.errors import InvalidOperationError
from tasktracker.services.folders import list_folders

INBOX_NAME = "Inbox"
MAX_REPORT_DAYS = 731  # two years


def build_overview(session: Session, user_id: int, today: date, days_ahead: int = 6) -> Overview:
    """What is going on now, and what is planned for today and the following days.

    A task belongs to a day when its planned date is that day, or when it has a planned
    block on the calendar that day.
    """
    days = [today + timedelta(days=i) for i in range(days_ahead + 1)]
    window_start = datetime.combine(today, time.min)
    window_end = datetime.combine(days[-1] + timedelta(days=1), time.min)

    blocks = calendar.list_blocks(session, user_id, window_start, window_end)
    tasks_by_day: dict[date, dict[int, Task]] = {day: {} for day in days}
    for task in tasks.list_tasks(session, user_id, planned_from=today, planned_to=days[-1]):
        tasks_by_day[task.planned_date][task.id] = task  # type: ignore[index]
    for block in blocks:
        day_tasks = tasks_by_day.get(block.starts_at.date())
        if day_tasks is not None and block.task is not None and block.kind is BlockKind.PLANNED:
            day_tasks.setdefault(block.task.id, block.task)

    plans = []
    for day in days:
        day_blocks = [b for b in blocks if b.starts_at.date() == day]
        day_tasks = tasks.sort_tasks(tasks_by_day[day].values())
        plans.append(
            DayPlan(
                day=day,
                tasks=[TaskRead.model_validate(t) for t in day_tasks],
                blocks=[TimeBlockRead.model_validate(b) for b in day_blocks],
                planned_minutes=_sum_minutes(day_blocks, BlockKind.PLANNED),
                tracked_minutes=_sum_minutes(day_blocks, BlockKind.TRACKED),
            )
        )

    running = calendar.get_running_timer(session, user_id)
    return Overview(
        today=today,
        active=[
            TaskRead.model_validate(t)
            for t in tasks.list_tasks(session, user_id, statuses=[TaskStatus.IN_PROGRESS])
        ],
        overdue=[
            TaskRead.model_validate(t) for t in tasks.list_tasks(session, user_id, overdue_on=today)
        ],
        days=plans,
        running_timer=TimeBlockRead.model_validate(running) if running else None,
    )


def folder_stats(session: Session, user_id: int, today: date) -> list[FolderStats]:
    """Status breakdown, completion and time per folder (plus the inbox, if used)."""
    owned = Task.user_id == user_id
    status_counts: dict[int | None, Counter[TaskStatus]] = defaultdict(Counter)
    for folder_id, status, count in session.execute(
        select(Task.folder_id, Task.status, func.count())
        .where(owned)
        .group_by(Task.folder_id, Task.status)
    ):
        status_counts[folder_id][status] = count

    estimates = dict(
        session.execute(
            select(Task.folder_id, func.coalesce(func.sum(Task.estimate_minutes), 0))
            .where(owned)
            .group_by(Task.folder_id)
        ).all()
    )
    overdue = dict(
        session.execute(
            select(Task.folder_id, func.count())
            .where(owned, tasks.overdue_clause(today))
            .group_by(Task.folder_id)
        ).all()
    )
    minutes = _minutes_by_folder(session, user_id)

    entries: list[tuple[int | None, str, str]] = [
        (f.id, f.name, f.color) for f in list_folders(session, user_id)
    ]
    if status_counts.get(None) or minutes.get(None):
        entries.insert(0, (None, INBOX_NAME, INBOX_COLOR))

    stats = []
    for folder_id, name, color in entries:
        counts = status_counts.get(folder_id, Counter())
        total = sum(counts.values())
        stats.append(
            FolderStats(
                folder_id=folder_id,
                name=name,
                color=color,
                total_tasks=total,
                open_tasks=total - counts[TaskStatus.DONE],
                overdue_tasks=overdue.get(folder_id, 0),
                completion_percent=_percent(counts[TaskStatus.DONE], total),
                statuses=[
                    StatusCount(status=s, count=counts[s], percent=_percent(counts[s], total))
                    for s in TaskStatus
                ],
                estimate_minutes=estimates.get(folder_id, 0),
                planned_minutes=minutes.get(folder_id, {}).get(BlockKind.PLANNED, 0),
                tracked_minutes=minutes.get(folder_id, {}).get(BlockKind.TRACKED, 0),
            )
        )
    return stats


def time_report(
    session: Session, user_id: int, starts_at: datetime, ends_at: datetime
) -> TimeReport:
    """Planned vs. tracked minutes in ``[starts_at, ends_at)`` per folder, per task (or
    appointment) and per day, and how many tasks were completed in that time.

    Blocks are clipped to the range, and split at midnight between days.
    """
    if ends_at <= starts_at:
        raise InvalidOperationError("The end of the range must be after its start")
    first_day, last_day = starts_at.date(), (ends_at - timedelta(microseconds=1)).date()
    day_count = (last_day - first_day).days + 1
    if day_count > MAX_REPORT_DAYS:
        raise InvalidOperationError("Pick a range of at most two years")

    by_folder: dict[int | None, Counter[BlockKind]] = defaultdict(Counter)
    by_item: dict[Hashable, Counter[BlockKind]] = defaultdict(Counter)
    by_day: dict[date, Counter[BlockKind]] = {
        first_day + timedelta(days=i): Counter() for i in range(day_count)
    }
    items: dict[Hashable, TimeBlock] = {}  # the first block seen for each task/appointment
    current = now()
    for block in calendar.list_blocks(session, user_id, starts_at, ends_at):
        key = block.task_id or ("appointment", block.display_title, block.effective_folder_id)
        items.setdefault(key, block)
        start, end = max(block.starts_at, starts_at), min(block.ends_at or current, ends_at)
        for day, seconds in _split_by_day(start, end):
            by_folder[block.effective_folder_id][block.kind] += seconds
            by_item[key][block.kind] += seconds
            by_day[day][block.kind] += seconds

    folders = {f.id: f for f in list_folders(session, user_id)}
    folder_rows = []
    for folder_id, seconds in by_folder.items():
        folder = folders.get(folder_id) if folder_id is not None else None
        folder_rows.append(
            FolderTime(
                folder_id=folder_id,
                name=folder.name if folder else INBOX_NAME,
                color=folder.color if folder else INBOX_COLOR,
                **_minutes(seconds),
            )
        )
    folder_rows.sort(key=lambda r: (-r.tracked_minutes, -r.planned_minutes, r.name.lower()))

    task_rows = [
        TaskTime(
            task_id=block.task_id,
            title=block.task.title if block.task else block.display_title,
            folder_id=block.effective_folder_id,
            color=block.color,
            status=block.task.status if block.task else None,
            **_minutes(by_item[key]),
        )
        for key, block in items.items()
    ]
    task_rows = [r for r in task_rows if r.planned_minutes or r.tracked_minutes]
    task_rows.sort(key=lambda r: (-r.tracked_minutes, -r.planned_minutes, r.title.lower()))

    completed = session.scalar(
        select(func.count(Task.id)).where(
            Task.user_id == user_id, Task.completed_at >= starts_at, Task.completed_at < ends_at
        )
    )
    return TimeReport(
        starts_at=starts_at,
        ends_at=ends_at,
        folders=folder_rows,
        tasks=task_rows,
        days=[DayTime(day=day, **_minutes(seconds)) for day, seconds in by_day.items()],
        planned_minutes=sum(r.planned_minutes for r in folder_rows),
        tracked_minutes=sum(r.tracked_minutes for r in folder_rows),
        completed_tasks=completed or 0,
    )


def _split_by_day(start: datetime, end: datetime) -> Iterator[tuple[date, float]]:
    """The seconds of ``[start, end)`` on each day it touches."""
    while start < end:
        stop = min(end, datetime.combine(start.date() + timedelta(days=1), time.min))
        yield start.date(), (stop - start).total_seconds()
        start = stop


def _minutes(seconds: Counter[BlockKind]) -> dict[str, int]:
    return {
        "planned_minutes": round(seconds[BlockKind.PLANNED] / 60),
        "tracked_minutes": round(seconds[BlockKind.TRACKED] / 60),
    }


def _minutes_by_folder(session: Session, user_id: int) -> dict[int | None, dict[BlockKind, int]]:
    """All-time planned and tracked minutes per folder (None: the inbox)."""
    folder_id = func.coalesce(Task.folder_id, TimeBlock.folder_id)
    stmt = (
        select(folder_id, TimeBlock.kind, TimeBlock.starts_at, TimeBlock.ends_at)
        .outerjoin(Task, TimeBlock.task_id == Task.id)
        .where(TimeBlock.user_id == user_id)
    )
    current = now()
    seconds: dict[int | None, dict[BlockKind, float]] = defaultdict(lambda: defaultdict(float))
    for fid, kind, block_start, block_end in session.execute(stmt):
        end = block_end or current
        if end > block_start:
            seconds[fid][kind] += (end - block_start).total_seconds()
    return {
        fid: {kind: round(total / 60) for kind, total in by_kind.items()}
        for fid, by_kind in seconds.items()
    }


def _sum_minutes(blocks: list[TimeBlock], kind: BlockKind) -> int:
    return sum(b.duration_minutes for b in blocks if b.kind is kind)


def _percent(part: int, total: int) -> float:
    return round(part / total * 100, 1) if total else 0.0
