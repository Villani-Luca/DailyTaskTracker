from datetime import date

from fastapi import APIRouter, Response

from tasktracker.api.deps import SessionDep
from tasktracker.schemas import FolderCreate, FolderRead, FolderStats, FolderUpdate
from tasktracker.services import folders, reports

router = APIRouter(prefix="/folders", tags=["folders"])


@router.get("", response_model=list[FolderRead])
def list_folders(session: SessionDep):
    return folders.list_folders(session)


@router.post("", response_model=FolderRead, status_code=201)
def create_folder(data: FolderCreate, session: SessionDep):
    return folders.create_folder(session, data)


@router.get("/stats", response_model=list[FolderStats])
def folder_stats(session: SessionDep, today: date | None = None):
    return reports.folder_stats(session, today or date.today())


@router.get("/{folder_id}", response_model=FolderRead)
def get_folder(folder_id: int, session: SessionDep):
    return folders.get_folder(session, folder_id)


@router.patch("/{folder_id}", response_model=FolderRead)
def update_folder(folder_id: int, data: FolderUpdate, session: SessionDep):
    return folders.update_folder(session, folder_id, data)


@router.delete("/{folder_id}", status_code=204)
def delete_folder(folder_id: int, session: SessionDep) -> Response:
    folders.delete_folder(session, folder_id)
    return Response(status_code=204)
