"""Saved-task-views endpoints — CRUD for user-defined task filters."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status

from app.db import SessionLocal
from app.saved_task_views import service
from app.saved_task_views.emoji import pick_emoji_for_view
from app.saved_task_views.schemas import (
    SavedTaskViewCreate,
    SavedTaskViewRead,
    SavedTaskViewUpdate,
)

router = APIRouter()


@router.get("/saved-task-views")
def list_views() -> dict[str, list[SavedTaskViewRead]]:
    with SessionLocal() as session:
        rows = service.list_views(session)
        return {"views": [SavedTaskViewRead.from_orm_row(r) for r in rows]}


@router.post("/saved-task-views", status_code=status.HTTP_201_CREATED)
def create_view(body: SavedTaskViewCreate) -> SavedTaskViewRead:
    icon = body.icon
    if icon is None:
        icon = pick_emoji_for_view(
            name=body.name,
            filters=body.filters,
            labels=body.filters.get("labels", []),
        )
    body_with_icon = body.model_copy(update={"icon": icon})
    with SessionLocal() as session:
        view = service.create_view(session, body_with_icon)
        return SavedTaskViewRead.from_orm_row(view)


@router.patch("/saved-task-views/{view_id}")
def update_view(view_id: int, body: SavedTaskViewUpdate) -> SavedTaskViewRead:
    with SessionLocal() as session:
        view = service.update_view(session, view_id, body)
        if view is None:
            raise HTTPException(status_code=404, detail="View not found")
        return SavedTaskViewRead.from_orm_row(view)


@router.delete("/saved-task-views/{view_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_view(view_id: int) -> Response:
    with SessionLocal() as session:
        try:
            ok = service.delete_view(session, view_id)
        except service.LastViewError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not ok:
            raise HTTPException(status_code=404, detail="View not found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)
