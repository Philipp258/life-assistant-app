"""Default saved task views, seeded at boot instead of via migration.

The task screen's first-run shape is deliberately small:

- Inbox: no filter, the default landing view.
- Mine: user-owned tasks.
- Assistant: assistant-owned tasks.

Saved views are user-owned UI state once the user has curated them. Boot
seeding creates these defaults when no saved views exist, and replaces
only untouched legacy first-run defaults from older releases.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.saved_task_views.models import SavedTaskView

DEFAULT_VIEW_NAME = "Tasks"
DEFAULT_VIEW_ICON: str | None = None
DEFAULT_VIEW_FILTERS: dict[str, object] = {}

TODAY_VIEW_NAME = "Today"
TODAY_VIEW_ICON = "☀️"
TODAY_VIEW_FILTERS: dict[str, object] = {"due": "today", "statuses": ["open", "scheduled"]}

LEGACY_MAIN_VIEW_NAME = "main"
LEGACY_MAIN_VIEW_FILTERS: dict[str, object] = {
    "due": None,
    "statuses": ["open", "scheduled", "waiting"],
}
LEGACY_ASSISTANTS_VIEW_NAME = "assistants"
LEGACY_ASSISTANTS_VIEW_FILTERS: dict[str, object] = {
    "due": None,
    "statuses": ["open", "scheduled", "waiting"],
    "assignee": "assistant",
}

INBOX_VIEW_NAME = "Inbox"
INBOX_VIEW_ICON = "📥"
INBOX_VIEW_FILTERS: dict[str, object] = {}
MINE_VIEW_NAME = "Mine"
MINE_VIEW_ICON = "👤"
MINE_VIEW_FILTERS: dict[str, object] = {"assignee": "user"}
ASSISTANT_VIEW_NAME = "Assistant"
ASSISTANT_VIEW_ICON = "🤖"
ASSISTANT_VIEW_FILTERS: dict[str, object] = {"assignee": "assistant"}


@dataclass(frozen=True)
class DefaultViewSpec:
    name: str
    icon: str
    filters: dict[str, object]
    is_default: bool = False


DEFAULT_SAVED_VIEWS: tuple[DefaultViewSpec, ...] = (
    DefaultViewSpec(
        name=INBOX_VIEW_NAME,
        icon=INBOX_VIEW_ICON,
        filters=INBOX_VIEW_FILTERS,
        is_default=True,
    ),
    DefaultViewSpec(
        name=MINE_VIEW_NAME,
        icon=MINE_VIEW_ICON,
        filters=MINE_VIEW_FILTERS,
    ),
    DefaultViewSpec(
        name=ASSISTANT_VIEW_NAME,
        icon=ASSISTANT_VIEW_ICON,
        filters=ASSISTANT_VIEW_FILTERS,
    ),
)


def _seed_default_views(db: Session) -> None:
    for idx, spec in enumerate(DEFAULT_SAVED_VIEWS):
        db.add(
            SavedTaskView(
                name=spec.name,
                icon=spec.icon,
                filters_json=dict(spec.filters),
                group_by="none",
                sort_index=idx,
                is_default=spec.is_default,
            )
        )


def _matches_untouched_view(
    view: SavedTaskView,
    *,
    name: str,
    icon: str | None,
    filters: dict[str, object],
    group_by: str = "none",
    sort_index: int = 0,
    is_default: bool = True,
) -> bool:
    return (
        view.name == name
        and view.icon == icon
        and view.filters_json == filters
        and view.group_by == group_by
        and view.sort_index == sort_index
        and view.is_default is is_default
    )


def _is_untouched_legacy_main_assistants(rows: list[SavedTaskView]) -> bool:
    if len(rows) != 2:
        return False
    main, assistants = rows
    return _matches_untouched_view(
        main,
        name=LEGACY_MAIN_VIEW_NAME,
        icon=None,
        filters=LEGACY_MAIN_VIEW_FILTERS,
        group_by="assignee",
        sort_index=0,
        is_default=True,
    ) and _matches_untouched_view(
        assistants,
        name=LEGACY_ASSISTANTS_VIEW_NAME,
        icon=None,
        filters=LEGACY_ASSISTANTS_VIEW_FILTERS,
        group_by="assignee",
        sort_index=1,
        is_default=False,
    )


def _is_untouched_legacy_default(rows: list[SavedTaskView]) -> bool:
    if _is_untouched_legacy_main_assistants(rows):
        return True
    if len(rows) != 1:
        return False
    view = rows[0]
    return _matches_untouched_view(
        view,
        name=TODAY_VIEW_NAME,
        icon=TODAY_VIEW_ICON,
        filters=TODAY_VIEW_FILTERS,
    ) or _matches_untouched_view(
        view,
        name=DEFAULT_VIEW_NAME,
        icon=DEFAULT_VIEW_ICON,
        filters=DEFAULT_VIEW_FILTERS,
    )


def ensure_default_saved_views(db: Session) -> bool:
    """Create first-run default views or replace untouched legacy defaults.

    Returns True if it changed rows, False when user-curated views were
    already present.
    """
    rows = list(
        db.scalars(select(SavedTaskView).order_by(SavedTaskView.sort_index, SavedTaskView.id))
    )
    if rows and not _is_untouched_legacy_default(rows):
        return False
    if rows:
        for row in rows:
            db.delete(row)
        db.flush()
    _seed_default_views(db)
    db.commit()
    return True
