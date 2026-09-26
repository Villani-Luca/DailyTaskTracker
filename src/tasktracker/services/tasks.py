from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date

from sqlalchemy import ColumnElement, Select, or_, select
from sqlalchemy.orm import Session, selectinload

from tasktracker.models import Comment, Priority, Task, TaskStatus, now
from tasktracker.schemas import CommentCreate, TaskCreate, TaskUpdate
from tasktracker.services.errors import NotFoundError
from tasktracker.services.folders import get_folder

_STATUS_RANK = {
    TaskStatus.IN_PROGRESS: 0,
    TaskStatus.TODO: 1,
    TaskStatus.BLOCKED: 2,
    TaskStatus.DONE: 3,
}
_PRIORITY_RANK = {Priority.HIGH: 0, Priority.MEDIUM: 1, Priority.LOW: 2}


def task_query(user_id: int) -> Select[tuple[Task]]:
    return (
        select(Task)
        .where(Task.user_id == user_id)
        .options(selectinload(Task.folder), selectinload(Task.time_blocks))
    )


def sort_tasks(tasks: Iterable[Task]) -> list[Task]:
    """Work in progress first, then by planned date, then by priority."""
    return sorted(
        tasks,
        key=lambda t: (
            _STATUS_RANK[t.status],
            t.planned_date or date.max,
            _PRIORITY_RANK[t.priority],
            t.id,
        ),
    )


def overdue_clause(today: date) -> ColumnElement[bool]:
    """Not done, and its planned day or due date is already behind us."""
    return (Task.status != TaskStatus.DONE) & or_(Task.planned_date < today, Task.due_date < today)


def list_tasks(
    session: Session,
    user_id: int,
    *,
    folder_id: int | None = None,
    inbox: bool = False,
    statuses: Sequence[TaskStatus] | None = None,
    planned_from: date | None = None,
    planned_to: date | None = None,
    overdue_on: date | None = None,
    search: str | None = None,
) -> list[Task]:
    stmt = task_query(user_id)
    if inbox:
        stmt = stmt.where(Task.folder_id.is_(None))
    elif folder_id is not None:
        stmt = stmt.where(Task.folder_id == folder_id)
    if statuses:
        stmt = stmt.where(Task.status.in_(statuses))
    if planned_from is not None:
        stmt = stmt.where(Task.planned_date >= planned_from)
    if planned_to is not None:
        stmt = stmt.where(Task.planned_date <= planned_to)
    if overdue_on is not None:
        stmt = stmt.where(overdue_clause(overdue_on))
    if search:
        stmt = stmt.where(Task.title.icontains(search, autoescape=True))
    return sort_tasks(session.scalars(stmt))


def get_task(session: Session, user_id: int, task_id: int) -> Task:
    task = session.scalar(task_query(user_id).where(Task.id == task_id))
    if task is None:
        raise NotFoundError("Task", task_id)
    return task


def create_task(session: Session, user_id: int, data: TaskCreate) -> Task:
    if data.folder_id is not None:
        get_folder(session, user_id, data.folder_id)
    task = Task(user_id=user_id, **data.model_dump(exclude={"status"}))
    set_status(task, data.status)
    session.add(task)
    session.commit()
    return task


def update_task(session: Session, user_id: int, task_id: int, data: TaskUpdate) -> Task:
    task = get_task(session, user_id, task_id)
    changes = data.changes()
    if changes.get("folder_id") is not None:
        get_folder(session, user_id, changes["folder_id"])
    if "status" in changes:
        set_status(task, changes.pop("status"))
    for field, value in changes.items():
        setattr(task, field, value)
    session.commit()
    return task


def set_status(task: Task, status: TaskStatus) -> None:
    """Change status, keeping ``completed_at`` and running timers consistent."""
    if status is task.status and (status is not TaskStatus.DONE or task.completed_at):
        return
    task.status = status
    if status is TaskStatus.DONE:
        task.completed_at = now()
        for block in task.time_blocks:
            if block.is_running:
                block.stop()
    else:
        task.completed_at = None


def delete_task(session: Session, user_id: int, task_id: int) -> None:
    """Delete a task together with its comments and calendar blocks."""
    session.delete(get_task(session, user_id, task_id))
    session.commit()


# --- Comments ------------------------------------------------------------------------


def list_comments(session: Session, user_id: int, task_id: int) -> list[Comment]:
    _ensure_task_exists(session, user_id, task_id)
    stmt = select(Comment).where(Comment.task_id == task_id).order_by(Comment.id)
    return list(session.scalars(stmt))


def add_comment(session: Session, user_id: int, task_id: int, data: CommentCreate) -> Comment:
    _ensure_task_exists(session, user_id, task_id)
    comment = Comment(task_id=task_id, body=data.body)
    session.add(comment)
    session.commit()
    return comment


def delete_comment(session: Session, user_id: int, comment_id: int) -> None:
    comment = session.get(Comment, comment_id)
    if comment is None or comment.task.user_id != user_id:
        raise NotFoundError("Comment", comment_id)
    session.delete(comment)
    session.commit()


def _ensure_task_exists(session: Session, user_id: int, task_id: int) -> None:
    task = session.get(Task, task_id)
    if task is None or task.user_id != user_id:
        raise NotFoundError("Task", task_id)
