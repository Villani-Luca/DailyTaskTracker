from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from tasktracker.api.deps import CurrentUser, SessionDep
from tasktracker.models import today as local_today
from tasktracker.schemas import LocalDateTime, Overview, TimeReport
from tasktracker.services import reports

router = APIRouter(tags=["reports"])


@router.get("/overview", response_model=Overview)
def overview(
    session: SessionDep,
    user: CurrentUser,
    days: Annotated[int, Query(ge=0, le=30)] = 6,
    today: date | None = None,
):
    return reports.build_overview(session, user.id, today or local_today(), days_ahead=days)


@router.get("/reports/time", response_model=TimeReport)
def time_report(
    starts_at: LocalDateTime, ends_at: LocalDateTime, session: SessionDep, user: CurrentUser
):
    return reports.time_report(session, user.id, starts_at, ends_at)
