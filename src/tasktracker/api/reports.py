from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Response

from tasktracker.api.deps import CurrentUser, SessionDep
from tasktracker.models import today as local_today
from tasktracker.schemas import LocalDateTime, Overview, TimeReport
from tasktracker.services import export, reports

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
    starts_at: LocalDateTime,
    ends_at: LocalDateTime,
    session: SessionDep,
    user: CurrentUser,
    folder_id: int | None = None,
    inbox: bool = False,
):
    """All folders, or only ``folder_id``'s time, or only the inbox's (``inbox=true``)."""
    return reports.time_report(
        session, user.id, starts_at, ends_at, folder_id=folder_id, inbox=inbox
    )


@router.get(
    "/reports/time.xlsx",
    response_class=Response,
    responses={200: {"content": {export.XLSX_MEDIA_TYPE: {}}}},
)
def time_report_xlsx(
    starts_at: LocalDateTime,
    ends_at: LocalDateTime,
    session: SessionDep,
    user: CurrentUser,
    folder_id: int | None = None,
    inbox: bool = False,
) -> Response:
    """The same report as an Excel file, plus every calendar block in the range."""
    filename, content = export.time_report_xlsx(
        session, user.id, starts_at, ends_at, folder_id=folder_id, inbox=inbox
    )
    return Response(
        content,
        media_type=export.XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
