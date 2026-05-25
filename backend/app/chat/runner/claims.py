"""Task claim, eligibility, and terminal-state helpers.

All DB-backed. The cross-process run claim (`tasks.run_claimed_at`)
prevents two runners — typically an old uvicorn process and the new one
during `--reload` — from running the same task at once.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update

from app.chat.models import ChatSession
from app.datetime_utils import normalize_to_naive_utc, utc_now
from app.db import SessionLocal
from app.tasks.models import Task


# A `tasks.run_claimed_at` newer than this means a runner is actively
# mid-wake on the task; another runner (e.g. a freshly-restarted
# process's lifespan recovery) must not also run it. Generous so a long
# tool-heavy turn never looks stale to a peer; if a runner dies the
# claim goes stale after this and the watchdog reclaims the task.
RUN_CLAIM_TTL_SECONDS = 1800.0


def _get_task_for_session(session_id: int) -> Task | None:
    with SessionLocal() as db:
        chat = db.get(ChatSession, session_id)
        if chat is None or chat.task_id is None:
            return None
        return db.get(Task, chat.task_id)


def _run_claim_is_fresh(task: Task, *, now: datetime) -> bool:
    claimed = task.run_claimed_at
    if claimed is None:
        return False
    return (now - normalize_to_naive_utc(claimed)).total_seconds() < RUN_CLAIM_TTL_SECONDS


def _claim_task_run(task_id: int) -> None:
    """Stamp the run-claim. Direct UPDATE (not an ORM mutation) so it
    does not bump `tasks.updated_at` on every wake."""
    with SessionLocal() as db:
        db.execute(update(Task).where(Task.id == task_id).values(run_claimed_at=utc_now()))
        db.commit()


def _release_task_run(task_id: int) -> None:
    with SessionLocal() as db:
        db.execute(update(Task).where(Task.id == task_id).values(run_claimed_at=None))
        db.commit()


def should_start_task(task: Task, *, now: datetime | None = None) -> bool:
    """Return whether an assistant-owned task is eligible to run now.

    This is the single gate for autonomous task wake eligibility. Keep
    creation-time immediate wakes, direct session wakes, and watchdog/startup
    recovery in sync by using this helper instead of duplicating partial
    checks. Every task now has a chat session by invariant
    (`tasks.chat_session_id` is NOT NULL), so eligibility reduces to
    assignee + done state + `do_at`.
    """
    if task.is_done or task.assignee != "assistant":
        return False
    current = normalize_to_naive_utc(now) if now is not None else utc_now()
    if _run_claim_is_fresh(task, now=current):
        # A live runner (possibly in another process — after a deploy /
        # uvicorn --reload, both the old and new process briefly exist)
        # is mid-wake on this task. Not eligible; the watchdog retries
        # once the claim clears or goes stale.
        return False
    return task.do_at is None or normalize_to_naive_utc(task.do_at) <= current


def _task_in_terminal_state(task: Task, *, now: datetime | None = None) -> bool:
    """Whether `task` is currently in a terminal state for the runner.

    Mirrors the branch in `_persist_wake_outcome`: done, handed to user,
    or scheduled into the future. Used after a task wake to decide
    whether to wake the main session (terminal) or skip it (still in
    flight) — main is interrupted only on real terminal transitions.
    """
    current = normalize_to_naive_utc(now) if now is not None else utc_now()
    if task.is_done:
        return True
    if task.assignee != "assistant":
        return True
    if task.do_at is not None and normalize_to_naive_utc(task.do_at) > current:
        return True
    return False


def list_in_flight_tasks() -> list[Task]:
    """Tasks whose autonomous wake is eligible to run right now.

    "Eligible" is defined by `should_start_task`: assistant-owned, not
    done, and `do_at` is unset OR has already passed. A future `do_at`
    keeps the task invisible to the watchdog until its time comes — the
    same mechanism `reschedule_task` uses to defer a task without losing
    its chat history. Every task has a chat session by invariant.

    Returns full Task rows (not just session IDs) so the watchdog can
    compute per-task backoff (`_gap_for`) without an N+1 fetch.
    """
    now = utc_now()
    with SessionLocal() as db:
        candidates = db.scalars(
            select(Task).where(
                Task.is_done.is_(False),
                Task.assignee == "assistant",
            )
        ).all()
    return [task for task in candidates if should_start_task(task, now=now)]
