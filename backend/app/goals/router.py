"""Goals endpoints — durable outcomes linked to tasks."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.db import SessionLocal
from app.goals import service
from app.goals.schemas import (
    GoalCreate,
    GoalDetailRead,
    GoalEventCreate,
    GoalEventRead,
    GoalRead,
    GoalUpdate,
    goal_event_to_read,
    goal_to_detail,
    goal_to_read,
)

router = APIRouter()


@router.get("/goals")
def list_goals(done: bool | None = Query(default=None)) -> dict[str, list[GoalRead]]:
    with SessionLocal() as session:
        return {"goals": [goal_to_read(goal) for goal in service.list_goals(session, done=done)]}


@router.post("/goals", status_code=status.HTTP_201_CREATED)
def create_goal(body: GoalCreate) -> GoalRead:
    with SessionLocal() as session:
        try:
            goal = service.create_goal(session, body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return goal_to_read(goal)


@router.get("/goals/{goal_id}")
def get_goal(goal_id: int) -> GoalDetailRead:
    with SessionLocal() as session:
        goal = service.get_goal(session, goal_id)
        if goal is None:
            raise HTTPException(status_code=404, detail="Goal not found")
        return goal_to_detail(goal)


@router.patch("/goals/{goal_id}")
def update_goal(goal_id: int, body: GoalUpdate) -> GoalDetailRead:
    with SessionLocal() as session:
        goal = service.update_goal(session, goal_id, body)
        if goal is None:
            raise HTTPException(status_code=404, detail="Goal not found")
        return goal_to_detail(goal)


@router.post("/goals/{goal_id}/events", status_code=status.HTTP_201_CREATED)
def append_goal_event(goal_id: int, body: GoalEventCreate) -> GoalEventRead:
    with SessionLocal() as session:
        try:
            event = service.create_goal_event(session, goal_id, body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if event is None:
            raise HTTPException(status_code=404, detail="Goal not found")
        return goal_event_to_read(event)


@router.delete("/goals/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_goal(goal_id: int) -> Response:
    with SessionLocal() as session:
        ok = service.delete_goal(session, goal_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Goal not found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)
