"""Task-log identity for recurring assistant routines.

A recurring assistant task gets a stable `task_log_line` on the Task row.
Every cycle (each recurrence is a fresh row + chat) inherits the same
line, so the durable note at
`data/knowledge/Task Log/<task_log_line>.md` accumulates across cycles
even though task ids, chat sessions, and titles are not stable identity.

Identity is intentionally derived from the *current* title at creation
time so the underlying knowledge note remains human-readable, but it is
then frozen on the row — title edits never repoint the log.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.tasks.models import Task

TASK_LOG_FOLDER = "Task Log"

_SLUG_NONALNUM = re.compile(r"[^a-z0-9]+")
_MAX_SLUG_LEN = 96


def slugify_title(title: str) -> str:
    """Lowercase, dash-joined identity. Mirrors `knowledge.store.slugify`
    so log paths look like the rest of the knowledge tree."""
    s = title.strip().lower()
    s = _SLUG_NONALNUM.sub("-", s)
    s = s.strip("-")
    if len(s) > _MAX_SLUG_LEN:
        s = s[:_MAX_SLUG_LEN].rstrip("-")
    return s or "routine"


def is_recurring_assistant_task(
    *,
    assignee: str | None,
    interval_unit: str | None,
    interval_count: int | None,
) -> bool:
    """Identity is scoped to recurring assistant routines only.

    A one-shot scheduled assistant job has no recurrence to compress
    across cycles, so it does not get a stable log line. User-owned
    tasks do not start a new line; a paused routine may still retain an
    existing one for continuity when it resumes."""
    return assignee == "assistant" and interval_unit is not None and interval_count is not None


def should_expose_task_log(
    *,
    task_log_line: str | None,
) -> bool:
    """Whether this task's agent should see the durable log."""
    return task_log_line is not None


def task_log_path(line: str) -> str:
    """Knowledge-store-relative path for the log of a given identity."""
    return f"{TASK_LOG_FOLDER}/{line}.md"


def allocate_task_log_line(
    session: Session,
    *,
    title: str,
    exclude_task_id: int | None = None,
) -> str:
    """Pick a fresh `task_log_line` for a new recurring assistant task.

    Derives a slug from `title` and disambiguates with a `-2`, `-3`, …
    suffix when the slug is already taken by another task row. The
    column is not UNIQUE because pre-existing data may already collide
    after backfill; instead the allocator is the single writer that
    keeps fresh allocations distinct.
    """
    base = slugify_title(title)
    taken = {
        line
        for line in session.scalars(
            select(Task.task_log_line).where(Task.task_log_line.is_not(None))
        )
        if line
    }
    if exclude_task_id is not None:
        current = session.scalar(select(Task.task_log_line).where(Task.id == exclude_task_id))
        taken.discard(current)
    candidate = base
    suffix = 2
    while candidate in taken:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate
