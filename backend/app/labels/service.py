"""DB helpers for labels. No FastAPI concerns here."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.labels.models import Label
from app.labels.schemas import LabelCreate, LabelUpdate


class DuplicateSlugError(ValueError):
    """Raised when a create/update would collide with an existing slug."""


def list_labels(session: Session) -> list[Label]:
    return list(session.scalars(select(Label).order_by(Label.name)))


def get_label(session: Session, label_id: int) -> Label | None:
    return session.get(Label, label_id)


def get_label_by_slug(session: Session, slug: str) -> Label | None:
    return session.scalars(select(Label).where(Label.slug == slug)).first()


def create_label(session: Session, body: LabelCreate) -> Label:
    label = Label(**body.model_dump())
    session.add(label)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise DuplicateSlugError(f"slug '{body.slug}' already exists") from exc
    session.refresh(label)
    return label


def update_label(session: Session, label_id: int, body: LabelUpdate) -> Label | None:
    label = session.get(Label, label_id)
    if label is None:
        return None
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(label, field, value)
    session.commit()
    session.refresh(label)
    return label


def delete_label(session: Session, label_id: int) -> bool:
    label = session.get(Label, label_id)
    if label is None:
        return False
    session.delete(label)  # cascade deletes task_labels rows
    session.commit()
    return True
