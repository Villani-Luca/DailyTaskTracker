from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tasktracker.models import Folder
from tasktracker.schemas import FolderCreate, FolderUpdate
from tasktracker.services.errors import ConflictError, NotFoundError


def list_folders(session: Session, user_id: int) -> list[Folder]:
    stmt = select(Folder).where(Folder.user_id == user_id).order_by(func.lower(Folder.name))
    return list(session.scalars(stmt))


def get_folder(session: Session, user_id: int, folder_id: int) -> Folder:
    folder = session.get(Folder, folder_id)
    if folder is None or folder.user_id != user_id:
        raise NotFoundError("Folder", folder_id)
    return folder


def create_folder(session: Session, user_id: int, data: FolderCreate) -> Folder:
    _ensure_unique_name(session, user_id, data.name)
    folder = Folder(user_id=user_id, **data.model_dump())
    session.add(folder)
    session.commit()
    return folder


def update_folder(session: Session, user_id: int, folder_id: int, data: FolderUpdate) -> Folder:
    folder = get_folder(session, user_id, folder_id)
    changes = data.changes()
    if "name" in changes:
        _ensure_unique_name(session, user_id, changes["name"], exclude_id=folder_id)
    for field, value in changes.items():
        setattr(folder, field, value)
    session.commit()
    return folder


def delete_folder(session: Session, user_id: int, folder_id: int) -> None:
    """Delete a folder. Its tasks and appointments are kept and move to the inbox."""
    session.delete(get_folder(session, user_id, folder_id))
    session.commit()


def _ensure_unique_name(
    session: Session, user_id: int, name: str, exclude_id: int | None = None
) -> None:
    stmt = select(Folder.id).where(
        Folder.user_id == user_id, func.lower(Folder.name) == name.lower()
    )
    if exclude_id is not None:
        stmt = stmt.where(Folder.id != exclude_id)
    if session.scalar(stmt) is not None:
        raise ConflictError(f"A folder named {name!r} already exists")
