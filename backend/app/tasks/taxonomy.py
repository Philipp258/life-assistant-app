"""Server-side status predicates for task filters.

Saved views can filter tasks by a computed status:

    done       – is_done
    scheduled  – future do_at / future due_at / has an interval
    waiting    – assistant-owned and parked by the runner (stalled streak)
    open       – everything else (frontend calls this "working")

`status_predicate` returns a single `ColumnElement[bool]` you can drop
into a `WHERE`. This is filter logic only; the production mobile task UI
does not render grouped status sections.
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, and_, false, or_

from app.datetime_utils import utc_now
from app.tasks.models import Task


def status_predicate(statuses: list[str]) -> ColumnElement[bool]:
    """OR of per-status predicates. Empty list ⇒ match nothing."""
    if not statuses:
        return false()

    now = utc_now()

    # Shared building blocks. Frontend `isFuture(iso, now)` treats a
    # null timestamp as "not in the future", so `do_at IS NULL` is *not*
    # scheduled — it's working.
    do_future = Task.do_at.is_not(None) & (Task.do_at > now)
    due_future = Task.due_at.is_not(None) & (Task.due_at > now)
    has_interval = Task.interval_unit.is_not(None)
    scheduled_expr = do_future | due_future | has_interval

    clauses: list[ColumnElement[bool]] = []
    for status in statuses:
        if status == "done":
            clauses.append(Task.is_done.is_(True))
        elif status == "scheduled":
            clauses.append(and_(Task.is_done.is_(False), scheduled_expr))
        elif status == "waiting":
            # Mirrors `groupOf`'s `signal.isStalled` branch. The DB-backed
            # signal is `consecutive_stalls > 0` (see /api/tasks/activity).
            clauses.append(
                and_(
                    Task.is_done.is_(False),
                    Task.assignee == "assistant",
                    Task.consecutive_stalls > 0,
                    ~scheduled_expr,
                )
            )
        elif status == "open":
            # Frontend "working": not done, not scheduled, and not the
            # Assistant-stalled "waiting" bucket.
            clauses.append(
                and_(
                    Task.is_done.is_(False),
                    ~scheduled_expr,
                    or_(
                        Task.assignee != "assistant",
                        Task.consecutive_stalls == 0,
                    ),
                )
            )
        # Unknown statuses fall through; FastAPI's Literal validation in
        # the saved-views schema is the gate. The listing endpoint passes
        # raw strings, but mismatches just don't contribute to the OR.
    if not clauses:
        return false()
    return or_(*clauses)
