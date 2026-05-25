"""Labels endpoints — CRUD for task tagging."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status

from app.db import SessionLocal
from app.labels import service
from app.labels.schemas import LabelCreate, LabelRead, LabelUpdate

router = APIRouter()


@router.get("/labels")
def list_labels() -> dict[str, list[LabelRead]]:
    with SessionLocal() as session:
        rows = service.list_labels(session)
        return {"labels": [LabelRead.model_validate(label) for label in rows]}


@router.post("/labels", status_code=status.HTTP_201_CREATED)
def create_label(body: LabelCreate) -> LabelRead:
    with SessionLocal() as session:
        try:
            label = service.create_label(session, body)
        except service.DuplicateSlugError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return LabelRead.model_validate(label)


@router.patch("/labels/{label_id}")
def update_label(label_id: int, body: LabelUpdate) -> LabelRead:
    with SessionLocal() as session:
        label = service.update_label(session, label_id, body)
        if label is None:
            raise HTTPException(status_code=404, detail="Label not found")
        return LabelRead.model_validate(label)


@router.delete("/labels/{label_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_label(label_id: int) -> Response:
    with SessionLocal() as session:
        if not service.delete_label(session, label_id):
            raise HTTPException(status_code=404, detail="Label not found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)
