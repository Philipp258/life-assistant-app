"""Tasks endpoints — CRUD for atomic tasks."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import select

from app.chat import runner
from app.db import SessionLocal
from app.tasks import service
from app.tasks.models import Task
from app.tasks.schemas import TaskCreate, TaskRead, TaskUpdate, task_to_read

router = APIRouter()


@router.get("/tasks/activity")
def tasks_activity() -> dict[str, list[int]]:
    """Per-task wake-state buckets surfaced to the UI.

    - `active_session_ids`: sessions whose runner is mid-turn right now
      (in-memory, drives the "live" pulse).
    - `stalled_session_ids`: tasks whose last wake finished without
      reaching a terminal state. DB-backed so the bucket survives a
      process restart.
    - `errored_session_ids`: tasks whose last wake raised. DB-backed
      so the watchdog backoff signal stays visible across restarts.

    Polled every few seconds by `TasksScreen`.
    """
    with SessionLocal() as session:
        stalled = list(
            session.scalars(select(Task.chat_session_id).where(Task.consecutive_stalls > 0))
        )
        errored = list(
            session.scalars(select(Task.chat_session_id).where(Task.consecutive_errors > 0))
        )
    return {
        "active_session_ids": runner.list_active_sessions(),
        "stalled_session_ids": stalled,
        "errored_session_ids": errored,
    }


@router.get("/tasks")
def list_tasks(
    label: list[str] | None = Query(default=None),
    assignee: str | None = Query(default=None),
    status: list[str] | None = Query(default=None),
    due: str | None = Query(default=None),
    done: bool | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """List tasks for the two-axis Tasks screen.

    - no `done` → legacy slice (open-before-done) for old saved views.
    - `done=false` → open feed, last-activity order.
    - `done=true` → keyset-paginated done tail; response carries
      `next_cursor` (null when exhausted).

    `status` is still accepted but only applies to the legacy slice — the
    tri-tier inner grouping classifies scheduled/waiting client-side, so
    the redesigned client no longer sends it.
    """
    with SessionLocal() as session:
        if done is True:
            try:
                tasks, next_cursor = service.list_done_tasks(
                    session,
                    labels=label,
                    assignee=assignee,  # type: ignore[arg-type]
                    due=due,  # type: ignore[arg-type]
                    cursor=cursor,
                    limit=limit,
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            return {
                "tasks": [task_to_read(t) for t in tasks],
                "next_cursor": next_cursor,
            }
        tasks = service.list_tasks(
            session,
            labels=label,
            assignee=assignee,  # type: ignore[arg-type]
            statuses=status,  # type: ignore[arg-type]
            due=due,  # type: ignore[arg-type]
            done=done,
        )
        return {"tasks": [task_to_read(t) for t in tasks]}


@router.get("/tasks/{task_id}")
def get_task(task_id: int) -> TaskRead:
    with SessionLocal() as session:
        task = service.get_task(session, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task_to_read(task)


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
def create_task(body: TaskCreate) -> TaskRead:
    with SessionLocal() as session:
        try:
            task = service.create_task(session, body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return task_to_read(task)


@router.patch("/tasks/{task_id}")
def update_task(task_id: int, body: TaskUpdate) -> TaskRead:
    with SessionLocal() as session:
        try:
            task = service.update_task(session, task_id, body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task_to_read(task)


@router.post("/tasks/{task_id}/run-now")
def run_task_now(task_id: int) -> TaskRead:
    """Trigger an assistant task immediately, regardless of its `do_at`.

    Used by the "Run now" UI affordance on agent tasks. The endpoint is
    a no-op for done or user-assigned tasks (returns 409). For recurring
    tasks, the cadence anchor shifts to `now` because the next cycle is
    spawned off the previous `do_at`.
    """
    with SessionLocal() as session:
        task = service.get_task(session, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        if task.is_done or task.assignee != "assistant":
            raise HTTPException(
                status_code=409,
                detail="Run now only applies to active assistant tasks",
            )
        ran = service.run_task_now(session, task_id)
        assert ran is not None  # guarded above
        return task_to_read(ran)


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: int) -> Response:
    with SessionLocal() as session:
        ok = service.delete_task(session, task_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Task not found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)
