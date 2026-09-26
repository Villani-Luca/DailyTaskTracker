from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Response

from tasktracker.api.deps import CurrentUser, SessionDep
from tasktracker.models import TaskStatus
from tasktracker.schemas import (
    CommentCreate,
    CommentRead,
    TaskCreate,
    TaskRead,
    TaskUpdate,
    TimeBlockRead,
)
from tasktracker.services import tasks

router = APIRouter(tags=["tasks"])


@router.get("/tasks", response_model=list[TaskRead])
def list_tasks(
    session: SessionDep,
    user: CurrentUser,
    folder_id: int | None = None,
    inbox: bool = False,
    status: Annotated[list[TaskStatus] | None, Query()] = None,
    planned_from: date | None = None,
    planned_to: date | None = None,
    q: str | None = None,
):
    return tasks.list_tasks(
        session,
        user.id,
        folder_id=folder_id,
        inbox=inbox,
        statuses=status,
        planned_from=planned_from,
        planned_to=planned_to,
        search=q,
    )


@router.post("/tasks", response_model=TaskRead, status_code=201)
def create_task(data: TaskCreate, session: SessionDep, user: CurrentUser):
    return tasks.create_task(session, user.id, data)


@router.get("/tasks/{task_id}", response_model=TaskRead)
def get_task(task_id: int, session: SessionDep, user: CurrentUser):
    return tasks.get_task(session, user.id, task_id)


@router.patch("/tasks/{task_id}", response_model=TaskRead)
def update_task(task_id: int, data: TaskUpdate, session: SessionDep, user: CurrentUser):
    return tasks.update_task(session, user.id, task_id, data)


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int, session: SessionDep, user: CurrentUser) -> Response:
    tasks.delete_task(session, user.id, task_id)
    return Response(status_code=204)


@router.get("/tasks/{task_id}/blocks", response_model=list[TimeBlockRead])
def list_task_blocks(task_id: int, session: SessionDep, user: CurrentUser):
    """The task's calendar history, most recent first."""
    blocks = tasks.get_task(session, user.id, task_id).time_blocks
    return sorted(blocks, key=lambda b: b.starts_at, reverse=True)


@router.get("/tasks/{task_id}/comments", response_model=list[CommentRead])
def list_comments(task_id: int, session: SessionDep, user: CurrentUser):
    return tasks.list_comments(session, user.id, task_id)


@router.post("/tasks/{task_id}/comments", response_model=CommentRead, status_code=201)
def add_comment(task_id: int, data: CommentCreate, session: SessionDep, user: CurrentUser):
    return tasks.add_comment(session, user.id, task_id, data)


@router.delete("/comments/{comment_id}", status_code=204)
def delete_comment(comment_id: int, session: SessionDep, user: CurrentUser) -> Response:
    tasks.delete_comment(session, user.id, comment_id)
    return Response(status_code=204)
