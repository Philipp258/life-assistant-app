"""DB helpers for goals. No FastAPI concerns here."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.datetime_utils import utc_now
from app.goals.models import Goal, GoalEvent
from app.goals.schemas import GoalCreate, GoalEventCreate, GoalUpdate
from app.tasks.models import Task


def list_goals(session: Session, *, done: bool | None = None) -> list[Goal]:
    stmt = select(Goal)
    if done is not None:
        stmt = stmt.where(Goal.is_done.is_(done))
    stmt = stmt.order_by(Goal.is_done.asc(), Goal.updated_at.desc(), Goal.id.desc())
    return list(session.scalars(stmt))


def get_goal(session: Session, goal_id: int) -> Goal | None:
    return session.get(Goal, goal_id)


def _get_task_or_raise(session: Session, task_id: int) -> Task:
    task = session.get(Task, task_id)
    if task is None:
        raise ValueError(f"unknown task_id: {task_id}")
    return task


def append_goal_event(
    session: Session,
    goal_id: int,
    *,
    kind: str,
    body: str | None = None,
    task_id: int | None = None,
    commit: bool = True,
) -> GoalEvent | None:
    goal = get_goal(session, goal_id)
    if goal is None:
        return None
    if task_id is not None:
        _get_task_or_raise(session, task_id)
    event = GoalEvent(goal_id=goal_id, task_id=task_id, kind=kind, body=body)
    session.add(event)
    goal.updated_at = utc_now()
    session.flush()
    if commit:
        session.commit()
        session.refresh(event)
        session.refresh(goal)
    return event


def create_goal(session: Session, data: GoalCreate) -> Goal:
    goal = Goal(title=data.title, description=data.description)
    session.add(goal)
    session.flush()
    append_goal_event(
        session,
        goal.id,
        kind="created",
        body="Goal created.",
        commit=False,
    )
    for task_id in data.task_ids:
        task = _get_task_or_raise(session, task_id)
        task.goal_id = goal.id
        append_goal_event(
            session,
            goal.id,
            kind="task_linked",
            body=f"Task linked: {task.title}",
            task_id=task.id,
            commit=False,
        )
    session.commit()
    session.refresh(goal)
    return goal


def update_goal(session: Session, goal_id: int, patch: GoalUpdate) -> Goal | None:
    goal = get_goal(session, goal_id)
    if goal is None:
        return None
    data = patch.model_dump(exclude_unset=True)
    prev_done = goal.is_done
    for key, value in data.items():
        setattr(goal, key, value)
    if "is_done" in data:
        if goal.is_done and not prev_done:
            goal.completed_at = utc_now()
            append_goal_event(
                session,
                goal.id,
                kind="completed",
                body="Goal marked complete.",
                commit=False,
            )
        elif not goal.is_done and prev_done:
            goal.completed_at = None
            append_goal_event(
                session,
                goal.id,
                kind="reopened",
                body="Goal reopened.",
                commit=False,
            )
    elif any(key in data for key in ("title", "description")):
        append_goal_event(
            session,
            goal.id,
            kind="updated",
            body="Goal details updated.",
            commit=False,
        )
    session.commit()
    session.refresh(goal)
    return goal


def delete_goal(session: Session, goal_id: int) -> bool:
    goal = get_goal(session, goal_id)
    if goal is None:
        return False
    session.delete(goal)
    session.commit()
    return True


def create_goal_event(session: Session, goal_id: int, data: GoalEventCreate) -> GoalEvent | None:
    return append_goal_event(
        session,
        goal_id,
        kind=data.kind,
        body=data.body,
        task_id=data.task_id,
    )
