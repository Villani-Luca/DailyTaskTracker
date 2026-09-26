from fastapi import APIRouter, Response

from tasktracker.api.deps import CurrentUser, SessionDep
from tasktracker.models import BlockKind
from tasktracker.schemas import (
    LocalDateTime,
    TimeBlockCreate,
    TimeBlockRead,
    TimeBlockUpdate,
    TimerStart,
)
from tasktracker.services import calendar

router = APIRouter(tags=["calendar"])


@router.get("/blocks", response_model=list[TimeBlockRead])
def list_blocks(
    starts_at: LocalDateTime,
    ends_at: LocalDateTime,
    session: SessionDep,
    user: CurrentUser,
    kind: BlockKind | None = None,
):
    return calendar.list_blocks(session, user.id, starts_at, ends_at, kind)


@router.post("/blocks", response_model=TimeBlockRead, status_code=201)
def create_block(data: TimeBlockCreate, session: SessionDep, user: CurrentUser):
    return calendar.create_block(session, user.id, data)


@router.patch("/blocks/{block_id}", response_model=TimeBlockRead)
def update_block(block_id: int, data: TimeBlockUpdate, session: SessionDep, user: CurrentUser):
    return calendar.update_block(session, user.id, block_id, data)


@router.delete("/blocks/{block_id}", status_code=204)
def delete_block(block_id: int, session: SessionDep, user: CurrentUser) -> Response:
    calendar.delete_block(session, user.id, block_id)
    return Response(status_code=204)


@router.get("/timer", response_model=TimeBlockRead | None)
def get_timer(session: SessionDep, user: CurrentUser):
    return calendar.get_running_timer(session, user.id)


@router.post("/timer/start", response_model=TimeBlockRead)
def start_timer(data: TimerStart, session: SessionDep, user: CurrentUser):
    return calendar.start_timer(session, user.id, data.task_id)


@router.post("/timer/stop", response_model=TimeBlockRead | None)
def stop_timer(session: SessionDep, user: CurrentUser):
    return calendar.stop_timer(session, user.id)
