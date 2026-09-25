from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tasktracker.models import Folder
from tasktracker.schemas import FolderCreate, FolderUpdate
from tasktracker.services.errors import ConflictError, NotFoundError


def list_folders(session: Session) -> list[Folder]:
    return list(session.scalars(select(Folder).order_by(func.lower(Folder.name))))


def get_folder(session: Session, folder_id: int) -> Folder:
    folder = session.get(Folder, folder_id)
    if folder is None:
        raise NotFoundError("Folder", folder_id)
    return folder


def create_folder(session: Session, data: FolderCreate) -> Folder:
    _ensure_unique_name(session, data.name)
    folder = Folder(**data.model_dump())
    session.add(folder)
    session.commit()
    return folder


def update_folder(session: Session, folder_id: int, data: FolderUpdate) -> Folder:
    folder = get_folder(session, folder_id)
    changes = data.changes()
    if "name" in changes:
        _ensure_unique_name(session, changes["name"], exclude_id=folder_id)
    for field, value in changes.items():
        setattr(folder, field, value)
    session.commit()
    return folder


def delete_folder(session: Session, folder_id: int) -> None:
    """Delete a folder. Its tasks and appointments are kept and move to the inbox."""
    session.delete(get_folder(session, folder_id))
    session.commit()


def _ensure_unique_name(session: Session, name: str, exclude_id: int | None = None) -> None:
    stmt = select(Folder.id).where(func.lower(Folder.name) == name.lower())
    if exclude_id is not None:
        stmt = stmt.where(Folder.id != exclude_id)
    if session.scalar(stmt) is not None:
        raise ConflictError(f"A folder named {name!r} already exists")
