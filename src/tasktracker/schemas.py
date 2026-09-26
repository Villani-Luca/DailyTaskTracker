"""Pydantic models: what goes in and out of the API (and, later, of AI tools)."""

from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Annotated, Any, ClassVar

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from tasktracker.config import local_timezone
from tasktracker.models import BlockKind, Frequency, Priority, TaskStatus

HEX_COLOR = r"^#[0-9a-fA-F]{6}$"

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
OptionalTitle = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
Color = Annotated[str, StringConstraints(pattern=HEX_COLOR)]
Minutes = Annotated[int, Field(ge=0, le=100_000)]


def _to_local_naive(value: datetime) -> datetime:
    """Accept any ISO datetime; store it as naive local time (see models.py)."""
    if value.tzinfo is not None:
        value = value.astimezone(local_timezone()).replace(tzinfo=None)
    return value.replace(microsecond=0)


LocalDateTime = Annotated[datetime, AfterValidator(_to_local_naive)]


class ReadModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PatchModel(BaseModel):
    """Partial update: only the fields the client sent are applied.

    Fields in ``non_nullable`` may be omitted but not explicitly set to null.
    """

    non_nullable: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def _reject_nulls(self) -> PatchModel:
        nulled = sorted(
            f for f in self.model_fields_set & self.non_nullable if getattr(self, f) is None
        )
        if nulled:
            raise ValueError(f"{', '.join(nulled)} cannot be null")
        return self

    def changes(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)


# --- Users ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: Annotated[str, StringConstraints(max_length=100)]
    password: Annotated[str, StringConstraints(max_length=1024)]


class UserRead(ReadModel):
    id: int
    username: str


# --- Folders -------------------------------------------------------------------------


class FolderCreate(BaseModel):
    name: Name
    color: Color = "#2a78d6"
    description: str = ""


class FolderUpdate(PatchModel):
    non_nullable = frozenset({"name", "color", "description"})

    name: Name | None = None
    color: Color | None = None
    description: str | None = None


class FolderRead(ReadModel):
    id: int
    name: str
    color: str
    description: str
    created_at: datetime


# --- Tasks & comments ----------------------------------------------------------------


class TaskCreate(BaseModel):
    title: Title
    description: str = ""
    folder_id: int | None = None
    status: TaskStatus = TaskStatus.TODO
    priority: Priority = Priority.MEDIUM
    planned_date: date | None = None
    due_date: date | None = None
    estimate_minutes: Minutes | None = None


class TaskUpdate(PatchModel):
    non_nullable = frozenset({"title", "description", "status", "priority"})

    title: Title | None = None
    description: str | None = None
    folder_id: int | None = None
    status: TaskStatus | None = None
    priority: Priority | None = None
    planned_date: date | None = None
    due_date: date | None = None
    estimate_minutes: Minutes | None = None


class TaskRead(ReadModel):
    id: int
    folder_id: int | None
    color: str
    title: str
    description: str
    status: TaskStatus
    priority: Priority
    planned_date: date | None
    due_date: date | None
    estimate_minutes: int | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    tracked_minutes: int
    planned_minutes: int
    comment_count: int
    is_timer_running: bool


class CommentCreate(BaseModel):
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10_000)]


class CommentRead(ReadModel):
    id: int
    task_id: int
    body: str
    created_at: datetime


# --- Calendar ------------------------------------------------------------------------


class RecurrenceRule(BaseModel):
    """Repeat a planned block every ``interval`` days, weeks or months, up to ``until``."""

    frequency: Frequency
    interval: Annotated[int, Field(ge=1, le=99)] = 1
    # Weekly only, Monday = 0. Empty means the weekday of the first event.
    weekdays: Annotated[list[Annotated[int, Field(ge=0, le=6)]], Field(max_length=7)] = []
    until: date


class RecurrenceRead(ReadModel):
    id: int
    frequency: Frequency
    interval: int
    weekdays: list[int]
    until: date


class SeriesScope(enum.StrEnum):
    """Which events of a repeating series a change or a delete applies to."""

    THIS = "this"
    FOLLOWING = "following"  # this event and the planned ones after it
    ALL = "all"  # every planned event (delete only)


class TimeBlockCreate(BaseModel):
    kind: BlockKind = BlockKind.PLANNED
    task_id: int | None = None
    folder_id: int | None = None
    title: OptionalTitle = ""
    starts_at: LocalDateTime
    ends_at: LocalDateTime
    notes: str = ""
    recurrence: RecurrenceRule | None = None

    @model_validator(mode="after")
    def _check(self) -> TimeBlockCreate:
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        if self.task_id is None and not self.title:
            raise ValueError("an appointment needs a title (or link it to a task)")
        if self.recurrence is not None and self.kind is not BlockKind.PLANNED:
            raise ValueError("only planned blocks can repeat")
        return self


class TimeBlockUpdate(PatchModel):
    non_nullable = frozenset({"kind", "title", "starts_at", "ends_at", "notes"})

    kind: BlockKind | None = None
    task_id: int | None = None
    folder_id: int | None = None
    title: OptionalTitle | None = None
    starts_at: LocalDateTime | None = None
    ends_at: LocalDateTime | None = None
    notes: str | None = None
    recurrence: RecurrenceRule | None = None  # null: stop repeating after this event


class TimeBlockRead(ReadModel):
    id: int
    kind: BlockKind
    task_id: int | None
    folder_id: int | None  # the appointment's own folder (None for task blocks)
    effective_folder_id: int | None  # the folder the block is colored by
    title: str
    display_title: str
    color: str
    starts_at: datetime
    ends_at: datetime | None
    notes: str
    duration_minutes: int
    is_running: bool
    recurrence: RecurrenceRead | None


class TimerStart(BaseModel):
    task_id: int


# --- Overview & stats ----------------------------------------------------------------


class DayPlan(BaseModel):
    day: date
    tasks: list[TaskRead]
    blocks: list[TimeBlockRead]
    planned_minutes: int
    tracked_minutes: int


class Overview(BaseModel):
    today: date
    active: list[TaskRead]
    overdue: list[TaskRead]
    days: list[DayPlan]
    running_timer: TimeBlockRead | None


class StatusCount(BaseModel):
    status: TaskStatus
    count: int
    percent: float


class FolderStats(BaseModel):
    folder_id: int | None  # None = inbox
    name: str
    color: str
    total_tasks: int
    open_tasks: int
    overdue_tasks: int
    completion_percent: float
    statuses: list[StatusCount]
    estimate_minutes: int
    planned_minutes: int
    tracked_minutes: int


class FolderTime(BaseModel):
    folder_id: int | None
    name: str
    color: str
    planned_minutes: int
    tracked_minutes: int


class TaskTime(BaseModel):
    task_id: int | None  # None: an appointment, time not linked to a task
    title: str
    folder_id: int | None
    color: str
    status: TaskStatus | None
    planned_minutes: int
    tracked_minutes: int


class DayTime(BaseModel):
    day: date
    planned_minutes: int
    tracked_minutes: int


class TimeReport(BaseModel):
    starts_at: datetime
    ends_at: datetime
    folders: list[FolderTime]
    tasks: list[TaskTime]
    days: list[DayTime]
    planned_minutes: int
    tracked_minutes: int
    completed_tasks: int  # tasks marked done in the range
