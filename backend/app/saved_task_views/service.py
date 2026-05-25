"""DB helpers for saved task views. No FastAPI concerns here."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.saved_task_views.models import SavedTaskView
from app.saved_task_views.schemas import SavedTaskViewCreate, SavedTaskViewUpdate


class LastViewError(ValueError):
    """Raised when an op would leave zero saved views (UI requires >=1)."""


def list_views(session: Session) -> list[SavedTaskView]:
    stmt = select(SavedTaskView).order_by(SavedTaskView.sort_index, SavedTaskView.id)
    return list(session.scalars(stmt))


def create_view(session: Session, body: SavedTaskViewCreate) -> SavedTaskView:
    max_sort = session.scalar(
        select(SavedTaskView).order_by(SavedTaskView.sort_index.desc()).limit(1)
    )
    next_sort = (max_sort.sort_index + 1) if max_sort else 0
    view = SavedTaskView(
        name=body.name,
        icon=body.icon,
        filters_json=body.filters,
        group_by=body.group_by,
        sort_index=next_sort,
    )
    session.add(view)
    session.commit()
    session.refresh(view)
    return view


def update_view(session: Session, view_id: int, body: SavedTaskViewUpdate) -> SavedTaskView | None:
    view = session.get(SavedTaskView, view_id)
    if view is None:
        return None
    data = body.model_dump(exclude_unset=True)
    if data.get("is_default"):
        # Only one default at a time.
        session.query(SavedTaskView).update({"is_default": False})
    if "filters" in data:
        view.filters_json = data.pop("filters")
    for key, value in data.items():
        setattr(view, key, value)
    session.commit()
    session.refresh(view)
    return view


def delete_view(session: Session, view_id: int) -> bool:
    view = session.get(SavedTaskView, view_id)
    if view is None:
        return False
    if session.query(SavedTaskView).count() <= 1:
        raise LastViewError("cannot delete the last remaining view")
    if view.is_default:
        # Promote the lowest-sort_index remaining view so the system always
        # has exactly one default.
        replacement = session.scalars(
            select(SavedTaskView)
            .where(SavedTaskView.id != view.id)
            .order_by(SavedTaskView.sort_index, SavedTaskView.id)
            .limit(1)
        ).first()
        if replacement is not None:
            replacement.is_default = True
    session.delete(view)
    session.commit()
    return True
