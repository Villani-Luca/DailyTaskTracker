"""Sample data so a fresh install has something to look at (``tasktracker --demo``)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from tasktracker.models import BlockKind, Folder, Priority, TaskStatus
from tasktracker.schemas import CommentCreate, FolderCreate, TaskCreate, TimeBlockCreate
from tasktracker.services import calendar, folders, tasks

_FOLDERS = [
    ("Work", "#2a78d6", "Day job: sprints, reviews, meetings."),
    ("Personal", "#eb6834", "Errands, bills, health."),
    ("Learning", "#1baf7a", "Courses, books and experiments."),
]

# folder, title, status, priority, planned (days from today), estimate, due (days from today)
_TASKS = [
    ("Work", "Prepare sprint review slides", TaskStatus.IN_PROGRESS, Priority.HIGH, 0, 120, 1),
    ("Work", "Review pull requests", TaskStatus.TODO, Priority.MEDIUM, 0, 45, None),
    ("Work", "Fix login timeout bug", TaskStatus.BLOCKED, Priority.HIGH, -1, 90, None),
    ("Work", "Write Q4 roadmap draft", TaskStatus.TODO, Priority.MEDIUM, 2, 180, 5),
    ("Work", "Weekly report", TaskStatus.DONE, Priority.MEDIUM, -1, 30, None),
    ("Work", "Update onboarding docs", TaskStatus.DONE, Priority.LOW, -3, 60, None),
    ("Personal", "Book dentist appointment", TaskStatus.TODO, Priority.LOW, 0, 10, None),
    ("Personal", "Grocery shopping", TaskStatus.TODO, Priority.MEDIUM, 1, 45, None),
    ("Personal", "Plan weekend trip", TaskStatus.TODO, Priority.MEDIUM, 3, 60, None),
    ("Personal", "Pay electricity bill", TaskStatus.DONE, Priority.HIGH, -1, 10, 0),
    ("Learning", "FastAPI course: module 4", TaskStatus.IN_PROGRESS, Priority.MEDIUM, 1, 90, None),
    ("Learning", "Read DDIA chapter 5", TaskStatus.TODO, Priority.LOW, 4, 60, None),
    ("Learning", "Try Claude API tool use", TaskStatus.TODO, Priority.MEDIUM, None, 120, None),
]

# task title (or appointment title + folder), kind, day offset, start, end
_BLOCKS = [
    ("Fix login timeout bug", None, BlockKind.TRACKED, -1, (9, 0), (10, 30)),
    ("Weekly report", None, BlockKind.TRACKED, -1, (11, 0), (11, 40)),
    ("Pay electricity bill", None, BlockKind.TRACKED, -1, (17, 30), (17, 45)),
    ("FastAPI course: module 4", None, BlockKind.TRACKED, -2, (20, 0), (21, 0)),
    ("Prepare sprint review slides", None, BlockKind.PLANNED, 0, (9, 0), (11, 0)),
    ("Prepare sprint review slides", None, BlockKind.TRACKED, 0, (9, 5), (10, 20)),
    ("Review pull requests", None, BlockKind.PLANNED, 0, (11, 30), (12, 15)),
    ("Team planning", "Work", BlockKind.PLANNED, 0, (14, 0), (15, 0)),
    ("FastAPI course: module 4", None, BlockKind.PLANNED, 1, (9, 0), (10, 30)),
    ("Gym", "Personal", BlockKind.PLANNED, 1, (18, 0), (19, 0)),
    ("Write Q4 roadmap draft", None, BlockKind.PLANNED, 2, (10, 0), (13, 0)),
]

_COMMENTS = [
    ("Prepare sprint review slides", "Ask the team for the latest velocity numbers."),
    ("Prepare sprint review slides", "Structure: goals, demo, metrics, next sprint."),
    ("Fix login timeout bug", "Blocked: waiting for access to the auth service logs."),
]


def seed_demo_data(session_factory: sessionmaker[Session], today: date | None = None) -> bool:
    """Populate an empty database. Returns False (and does nothing) if folders exist."""
    today = today or date.today()

    def day(offset: int | None) -> date | None:
        return None if offset is None else today + timedelta(days=offset)

    with session_factory() as session:
        if session.scalar(select(func.count(Folder.id))):
            return False

        folder_ids = {
            name: folders.create_folder(
                session, FolderCreate(name=name, color=color, description=description)
            ).id
            for name, color, description in _FOLDERS
        }
        task_ids = {}
        for folder, title, status, priority, planned, estimate, due in _TASKS:
            task = tasks.create_task(
                session,
                TaskCreate(
                    title=title,
                    folder_id=folder_ids[folder],
                    status=status,
                    priority=priority,
                    planned_date=day(planned),
                    due_date=day(due),
                    estimate_minutes=estimate,
                ),
            )
            task_ids[title] = task.id

        for title, folder, kind, offset, start, end in _BLOCKS:
            block_day = today + timedelta(days=offset)
            is_appointment = folder is not None
            calendar.create_block(
                session,
                TimeBlockCreate(
                    kind=kind,
                    task_id=None if is_appointment else task_ids[title],
                    folder_id=folder_ids[folder] if is_appointment else None,
                    title=title if is_appointment else "",
                    starts_at=datetime.combine(block_day, time(*start)),
                    ends_at=datetime.combine(block_day, time(*end)),
                ),
            )

        for title, body in _COMMENTS:
            tasks.add_comment(session, task_ids[title], CommentCreate(body=body))
    return True
