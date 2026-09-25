"""ORM models.

All datetimes are naive *local* wall-clock time: this is a single-user app running on
your own machine, and the calendar speaks local time too, so there is no timezone to
reconcile.
"""

from __future__ import annotations

import enum
from datetime import date, datetime, timedelta

from sqlalchemy import Enum, ForeignKey, String, Text, func, select
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship

from tasktracker.db import Base

INBOX_COLOR = "#8a8f98"  # tasks and appointments that are not in a folder


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


class TaskStatus(enum.StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"


class Priority(enum.StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class BlockKind(enum.StrEnum):
    PLANNED = "planned"  # time you intend to spend: a task placed on the calendar, an appointment
    TRACKED = "tracked"  # time you actually spent: a timer, or time logged by hand


def _enum_column(enum_cls: type[enum.Enum]) -> Enum:
    """Store the enum *value* ("in_progress") as plain text, not the member name."""
    return Enum(
        enum_cls,
        values_callable=lambda members: [m.value for m in members],
        native_enum=False,
        length=20,
    )


class Folder(Base):
    __tablename__ = "folders"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    color: Mapped[str] = mapped_column(String(7))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=now)

    # Deleting a folder moves its tasks to the inbox (ON DELETE SET NULL).
    tasks: Mapped[list[Task]] = relationship(back_populates="folder", passive_deletes=True)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    folder_id: Mapped[int | None] = mapped_column(
        ForeignKey("folders.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[TaskStatus] = mapped_column(
        _enum_column(TaskStatus), default=TaskStatus.TODO, index=True
    )
    priority: Mapped[Priority] = mapped_column(_enum_column(Priority), default=Priority.MEDIUM)
    planned_date: Mapped[date | None] = mapped_column(index=True)
    due_date: Mapped[date | None]
    estimate_minutes: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(default=now)
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now)
    completed_at: Mapped[datetime | None]

    folder: Mapped[Folder | None] = relationship(back_populates="tasks")
    comments: Mapped[list[Comment]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Comment.id",
    )
    # No delete-orphan: unlinking a block from its task turns it into an appointment.
    time_blocks: Mapped[list[TimeBlock]] = relationship(
        back_populates="task",
        cascade="all",
        passive_deletes=True,
        order_by="TimeBlock.starts_at",
    )

    @property
    def color(self) -> str:
        return self.folder.color if self.folder else INBOX_COLOR

    @property
    def tracked_minutes(self) -> int:
        return sum(b.duration_minutes for b in self.time_blocks if b.kind is BlockKind.TRACKED)

    @property
    def planned_minutes(self) -> int:
        return sum(b.duration_minutes for b in self.time_blocks if b.kind is BlockKind.PLANNED)

    @property
    def is_timer_running(self) -> bool:
        return any(b.is_running for b in self.time_blocks)


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=now)

    task: Mapped[Task] = relationship(back_populates="comments")


Task.comment_count = column_property(
    select(func.count(Comment.id)).where(Comment.task_id == Task.id).scalar_subquery()
)


class TimeBlock(Base):
    """A span of time on the calendar.

    Linked to a task, or standalone (an appointment) with its own title and optional
    folder. A tracked block whose ``ends_at`` is NULL is a running timer.
    """

    __tablename__ = "time_blocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[BlockKind] = mapped_column(_enum_column(BlockKind), index=True)
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    folder_id: Mapped[int | None] = mapped_column(ForeignKey("folders.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(200), default="")
    starts_at: Mapped[datetime] = mapped_column(index=True)
    ends_at: Mapped[datetime | None]
    notes: Mapped[str] = mapped_column(Text, default="")

    task: Mapped[Task | None] = relationship(back_populates="time_blocks")
    folder: Mapped[Folder | None] = relationship()

    @property
    def effective_folder(self) -> Folder | None:
        """A task's block takes the task's folder; an appointment uses its own."""
        return self.task.folder if self.task is not None else self.folder

    @property
    def effective_folder_id(self) -> int | None:
        folder = self.effective_folder
        return folder.id if folder else None

    @property
    def color(self) -> str:
        folder = self.effective_folder
        return folder.color if folder else INBOX_COLOR

    @property
    def display_title(self) -> str:
        if self.title:
            return self.title
        return self.task.title if self.task is not None else "Untitled"

    @property
    def is_running(self) -> bool:
        return self.ends_at is None

    @property
    def duration_minutes(self) -> int:
        end = self.ends_at or now()
        return max(0, round((end - self.starts_at).total_seconds() / 60))

    def stop(self) -> None:
        """Stop a running timer (a block always ends after it starts)."""
        self.ends_at = max(now(), self.starts_at + timedelta(seconds=1))
