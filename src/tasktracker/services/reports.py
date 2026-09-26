"""Read-only views: the daily overview, per-folder statistics and time reports."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from tasktracker.models import INBOX_COLOR, BlockKind, Task, TaskStatus, TimeBlock, now
from tasktracker.schemas import (
    DayPlan,
    FolderStats,
    FolderTime,
    Overview,
    StatusCount,
    TaskRead,
    TimeBlockRead,
    TimeReport,
)
from tasktracker.services import calendar, tasks
from tasktracker.services.folders import list_folders

INBOX_NAME = "Inbox"


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
    """Planned vs. tracked minutes per folder, clipped to ``[starts_at, ends_at)``."""
    minutes = _minutes_by_folder(session, user_id, starts_at, ends_at)
    folders = {f.id: f for f in list_folders(session, user_id)}
    rows = []
    for folder_id, by_kind in minutes.items():
        folder = folders.get(folder_id) if folder_id is not None else None
        rows.append(
            FolderTime(
                folder_id=folder_id,
                name=folder.name if folder else INBOX_NAME,
                color=folder.color if folder else INBOX_COLOR,
                planned_minutes=by_kind.get(BlockKind.PLANNED, 0),
                tracked_minutes=by_kind.get(BlockKind.TRACKED, 0),
            )
        )
    rows.sort(key=lambda r: (-r.tracked_minutes, -r.planned_minutes, r.name.lower()))
    return TimeReport(
        starts_at=starts_at,
        ends_at=ends_at,
        folders=rows,
        planned_minutes=sum(r.planned_minutes for r in rows),
        tracked_minutes=sum(r.tracked_minutes for r in rows),
    )


def _minutes_by_folder(
    session: Session,
    user_id: int,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
) -> dict[int | None, dict[BlockKind, int]]:
    folder_id = func.coalesce(Task.folder_id, TimeBlock.folder_id)
    stmt = (
        select(folder_id, TimeBlock.kind, TimeBlock.starts_at, TimeBlock.ends_at)
        .outerjoin(Task, TimeBlock.task_id == Task.id)
        .where(TimeBlock.user_id == user_id)
    )
    if starts_at is not None:
        stmt = stmt.where(or_(TimeBlock.ends_at.is_(None), TimeBlock.ends_at > starts_at))
    if ends_at is not None:
        stmt = stmt.where(TimeBlock.starts_at < ends_at)

    current = now()
    seconds: dict[int | None, dict[BlockKind, float]] = defaultdict(lambda: defaultdict(float))
    for fid, kind, block_start, block_end in session.execute(stmt):
        start = max(block_start, starts_at) if starts_at else block_start
        end = block_end or current
        end = min(end, ends_at) if ends_at else end
        if end > start:
            seconds[fid][kind] += (end - start).total_seconds()
    return {
        fid: {kind: round(total / 60) for kind, total in by_kind.items()}
        for fid, by_kind in seconds.items()
    }


def _sum_minutes(blocks: list[TimeBlock], kind: BlockKind) -> int:
    return sum(b.duration_minutes for b in blocks if b.kind is kind)


def _percent(part: int, total: int) -> float:
    return round(part / total * 100, 1) if total else 0.0
