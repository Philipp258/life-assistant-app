from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.datetime_utils import UtcDatetime

if TYPE_CHECKING:
    from app.goals.models import Goal, GoalEvent


GoalEventKind = Literal[
    "created",
    "updated",
    "note",
    "task_linked",
    "task_unlinked",
    "task_completed",
    "task_reopened",
    "completed",
    "reopened",
]


class GoalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    is_done: bool
    open_tasks_count: int
    done_tasks_count: int
    created_at: UtcDatetime
    updated_at: UtcDatetime
    completed_at: UtcDatetime | None


class GoalEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    goal_id: int
    task_id: int | None
    task_title: str | None
    kind: str
    body: str | None
    created_at: UtcDatetime


class GoalDetailRead(GoalRead):
    tasks: list["TaskRead"]
    events: list[GoalEventRead]


class GoalCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    task_ids: list[int] = Field(default_factory=list)


class GoalUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    is_done: bool | None = None


class GoalEventCreate(BaseModel):
    kind: GoalEventKind = "note"
    body: str | None = None
    task_id: int | None = None


def goal_to_read(goal: Goal) -> GoalRead:
    done = sum(1 for task in goal.tasks if task.is_done)
    total = len(goal.tasks)
    return GoalRead(
        id=goal.id,
        title=goal.title,
        description=goal.description,
        is_done=goal.is_done,
        open_tasks_count=total - done,
        done_tasks_count=done,
        created_at=goal.created_at,
        updated_at=goal.updated_at,
        completed_at=goal.completed_at,
    )


def goal_event_to_read(event: GoalEvent) -> GoalEventRead:
    return GoalEventRead(
        id=event.id,
        goal_id=event.goal_id,
        task_id=event.task_id,
        task_title=event.task.title if event.task is not None else None,
        kind=event.kind,
        body=event.body,
        created_at=event.created_at,
    )


def goal_to_detail(goal: Goal) -> GoalDetailRead:
    from app.tasks.schemas import task_to_read

    base = goal_to_read(goal).model_dump()
    tasks = sorted(
        goal.tasks,
        key=lambda task: (
            task.is_done,
            -task.updated_at.timestamp(),
            -task.id,
        ),
    )
    return GoalDetailRead(
        **base,
        tasks=[task_to_read(task) for task in tasks],
        events=[goal_event_to_read(event) for event in goal.events],
    )


from app.tasks.schemas import TaskRead  # noqa: E402

GoalDetailRead.model_rebuild()
