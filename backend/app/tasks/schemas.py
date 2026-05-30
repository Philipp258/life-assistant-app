from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.datetime_utils import UtcDatetime, normalize_to_naive_utc, utc_now

if TYPE_CHECKING:
    from app.tasks.models import Task

IntervalUnit = Literal["hour", "day", "week"]
TaskState = Literal["running", "up_next", "yours", "done"]
Assignee = Literal["user", "assistant"]
TaskKind = Literal[
    "routine",
    "scheduled-job",
    "job",
    "deadline",
    "scheduled-todo",
    "todo",
]


def _derive_state(
    is_done: bool,
    assignee: Assignee,
    do_at: datetime | None,
) -> TaskState:
    if is_done:
        return "done"
    if assignee == "user":
        return "yours"
    if do_at is not None and normalize_to_naive_utc(do_at) > utc_now():
        return "up_next"
    return "running"


def compute_kind(
    assignee: Assignee,
    do_at: datetime | None,
    due_at: datetime | None,
    interval_unit: IntervalUnit | None,
) -> TaskKind:
    """Derive UI / vocabulary label from field combo. Pure function."""
    if assignee == "assistant":
        if interval_unit is not None:
            return "routine"
        if do_at is not None:
            return "scheduled-job"
        return "job"
    # assignee == "user"
    if due_at is not None:
        return "deadline"
    if do_at is not None:
        return "scheduled-todo"
    return "todo"


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    is_done: bool
    assignee: Assignee
    chat_session_id: int
    goal_id: int | None
    goal_title: str | None
    do_at: UtcDatetime | None
    due_at: UtcDatetime | None
    interval_unit: IntervalUnit | None
    interval_count: int | None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    completed_at: UtcDatetime | None

    state: TaskState
    kind: TaskKind


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    assignee: Assignee = "user"
    do_at: datetime | None = None
    due_at: datetime | None = None
    interval_unit: IntervalUnit | None = None
    interval_count: int | None = Field(default=None, ge=1)
    goal_id: int | None = None

    @field_validator("do_at", "due_at", mode="after")
    @classmethod
    def _normalize_datetimes(cls, value: datetime | None) -> datetime | None:
        # DB columns are naive UTC. Clients may send `+00:00`, `Z`, or any
        # offset — coerce to naive UTC at the boundary so internal
        # comparisons (runner due-at, scheduler) stay aware-vs-aware free.
        return normalize_to_naive_utc(value)

    @model_validator(mode="after")
    def _validate_interval_pair(self) -> "TaskCreate":
        if (self.interval_unit is None) != (self.interval_count is None):
            raise ValueError("interval_unit and interval_count must be provided together")
        return self


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    is_done: bool | None = None
    assignee: Assignee | None = None
    do_at: datetime | None = None
    due_at: datetime | None = None
    interval_unit: IntervalUnit | None = None
    interval_count: int | None = Field(default=None, ge=1)
    goal_id: int | None = None

    @field_validator("do_at", "due_at", mode="after")
    @classmethod
    def _normalize_datetimes(cls, value: datetime | None) -> datetime | None:
        return normalize_to_naive_utc(value)

    @model_validator(mode="after")
    def _validate_interval_pair(self) -> "TaskUpdate":
        unit_set = "interval_unit" in self.model_fields_set
        count_set = "interval_count" in self.model_fields_set
        if unit_set != count_set:
            raise ValueError("interval_unit and interval_count must be updated together")
        if unit_set and count_set and (self.interval_unit is None) != (self.interval_count is None):
            raise ValueError("interval_unit and interval_count must both be null or both set")
        return self


def task_to_read(task: Task) -> TaskRead:
    return TaskRead(
        id=task.id,
        title=task.title,
        description=task.description,
        is_done=task.is_done,
        assignee=task.assignee,
        chat_session_id=task.chat_session_id,
        goal_id=getattr(task, "goal_id", None),
        goal_title=task.goal.title if getattr(task, "goal", None) is not None else None,
        do_at=task.do_at,
        due_at=task.due_at,
        interval_unit=task.interval_unit,
        interval_count=task.interval_count,
        created_at=task.created_at,
        updated_at=task.updated_at,
        completed_at=task.completed_at,
        state=_derive_state(task.is_done, task.assignee, task.do_at),
        kind=compute_kind(task.assignee, task.do_at, task.due_at, task.interval_unit),
    )
