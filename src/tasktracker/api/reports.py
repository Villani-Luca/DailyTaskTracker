from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from tasktracker.api.deps import SessionDep
from tasktracker.schemas import LocalDateTime, Overview, TimeReport
from tasktracker.services import reports

router = APIRouter(tags=["reports"])


@router.get("/overview", response_model=Overview)
def overview(
    session: SessionDep,
    days: Annotated[int, Query(ge=0, le=30)] = 6,
    today: date | None = None,
):
    return reports.build_overview(session, today or date.today(), days_ahead=days)


@router.get("/reports/time", response_model=TimeReport)
def time_report(starts_at: LocalDateTime, ends_at: LocalDateTime, session: SessionDep):
    return reports.time_report(session, starts_at, ends_at)
