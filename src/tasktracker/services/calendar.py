"""Calendar blocks (planned time, tracked time, appointments) and the task timer."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session, selectinload

from tasktracker.models import BlockKind, Task, TaskStatus, TimeBlock, now
from tasktracker.schemas import TimeBlockCreate, TimeBlockUpdate
from tasktracker.services.errors import InvalidOperationError, NotFoundError
from tasktracker.services.folders import get_folder
from tasktracker.services.tasks import get_task, set_status


def _block_query() -> Select[tuple[TimeBlock]]:
    return select(TimeBlock).options(
        selectinload(TimeBlock.task).selectinload(Task.folder),
        selectinload(TimeBlock.folder),
    )


def list_blocks(
    session: Session,
    starts_at: datetime,
    ends_at: datetime,
    kind: BlockKind | None = None,
) -> list[TimeBlock]:
    """Blocks overlapping ``[starts_at, ends_at)``, including a running timer."""
    stmt = (
        _block_query()
        .where(
            TimeBlock.starts_at < ends_at,
            or_(TimeBlock.ends_at.is_(None), TimeBlock.ends_at > starts_at),
        )
        .order_by(TimeBlock.starts_at)
    )
    if kind is not None:
        stmt = stmt.where(TimeBlock.kind == kind)
    return list(session.scalars(stmt))


def get_block(session: Session, block_id: int) -> TimeBlock:
    block = session.scalar(_block_query().where(TimeBlock.id == block_id))
    if block is None:
        raise NotFoundError("Time block", block_id)
    return block


def create_block(session: Session, data: TimeBlockCreate) -> TimeBlock:
    block = TimeBlock(**data.model_dump(exclude={"task_id"}))
    if data.task_id is not None:
        block.task = get_task(session, data.task_id)
        block.folder_id = None  # task blocks are colored by the task's folder
    elif data.folder_id is not None:
        get_folder(session, data.folder_id)

    if block.task is not None and block.kind is BlockKind.PLANNED:
        _follow_plan(block.task, old_day=None, new_day=block.starts_at.date())
    session.add(block)
    session.commit()
    return block


def update_block(session: Session, block_id: int, data: TimeBlockUpdate) -> TimeBlock:
    block = get_block(session, block_id)
    changes = data.changes()
    old_day = block.starts_at.date()

    if block.is_running and changes.get("kind", block.kind) is not block.kind:
        raise InvalidOperationError("Stop the timer before changing this block's kind")
    if "task_id" in changes:
        task_id = changes.pop("task_id")
        block.task = get_task(session, task_id) if task_id is not None else None
    if changes.get("folder_id") is not None:
        get_folder(session, changes["folder_id"])
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
    session.commit()
    return block


def delete_block(session: Session, block_id: int) -> None:
    session.delete(get_block(session, block_id))
    session.commit()


def _follow_plan(task: Task, old_day: date | None, new_day: date) -> None:
    """Placing a task on the calendar plans it for that day.

    The planned date only follows the block when it was unset or matched the block's
    previous day, so a date you picked deliberately is never overwritten.
    """
    if task.planned_date is None or task.planned_date == old_day:
        task.planned_date = new_day


# --- Timer ---------------------------------------------------------------------------


def get_running_timer(session: Session) -> TimeBlock | None:
    stmt = _block_query().where(TimeBlock.kind == BlockKind.TRACKED, TimeBlock.ends_at.is_(None))
    return session.scalars(stmt).first()


def start_timer(session: Session, task_id: int) -> TimeBlock:
    """Start tracking time on a task. Only one timer runs at a time."""
    task = get_task(session, task_id)
    running = get_running_timer(session)
    if running is not None:
        if running.task_id == task_id:
            return running
        running.stop()

    set_status(task, TaskStatus.IN_PROGRESS)
    block = TimeBlock(kind=BlockKind.TRACKED, task=task, starts_at=now(), ends_at=None)
    session.add(block)
    session.commit()
    return block


def stop_timer(session: Session) -> TimeBlock | None:
    running = get_running_timer(session)
    if running is None:
        return None
    running.stop()
    session.commit()
    return running
