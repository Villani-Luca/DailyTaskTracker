from datetime import date

from fastapi import APIRouter, Response

from tasktracker.api.deps import CurrentUser, SessionDep
from tasktracker.models import today as local_today
from tasktracker.schemas import FolderCreate, FolderRead, FolderStats, FolderUpdate
from tasktracker.services import folders, reports

router = APIRouter(prefix="/folders", tags=["folders"])


@router.get("", response_model=list[FolderRead])
def list_folders(session: SessionDep, user: CurrentUser):
    return folders.list_folders(session, user.id)


@router.post("", response_model=FolderRead, status_code=201)
def create_folder(data: FolderCreate, session: SessionDep, user: CurrentUser):
    return folders.create_folder(session, user.id, data)


@router.get("/stats", response_model=list[FolderStats])
def folder_stats(session: SessionDep, user: CurrentUser, today: date | None = None):
    return reports.folder_stats(session, user.id, today or local_today())


@router.get("/{folder_id}", response_model=FolderRead)
def get_folder(folder_id: int, session: SessionDep, user: CurrentUser):
    return folders.get_folder(session, user.id, folder_id)


@router.patch("/{folder_id}", response_model=FolderRead)
def update_folder(folder_id: int, data: FolderUpdate, session: SessionDep, user: CurrentUser):
    return folders.update_folder(session, user.id, folder_id, data)


@router.delete("/{folder_id}", status_code=204)
def delete_folder(folder_id: int, session: SessionDep, user: CurrentUser) -> Response:
    folders.delete_folder(session, user.id, folder_id)
    return Response(status_code=204)
