from fastapi import APIRouter

from tasktracker.api.deps import CurrentUser, SessionDep
from tasktracker.schemas import ImportPreview, ImportRequest, ImportResult, ImportSource
from tasktracker.services import imports

router = APIRouter(prefix="/import", tags=["import"])


@router.post("/preview", response_model=ImportPreview)
def preview_import(data: ImportSource, session: SessionDep, user: CurrentUser):
    """Read an .ics file, an email (.eml), pasted text or a calendar link, and say what
    importing it would do. Nothing is saved."""
    return imports.preview(session, user.id, data)


@router.post("", response_model=ImportResult)
def import_events(data: ImportRequest, session: SessionDep, user: CurrentUser):
    """Import the events picked in the preview (``keys``; all when omitted) into a folder."""
    return imports.import_events(session, user.id, data)
