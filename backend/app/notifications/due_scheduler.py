"""Periodic scheduler that fires a Web Push when a task's due_at passes.

Lives in lifespan, not the runner: due dates are user-facing reminders,
not autonomous-agent triggers. Pile-on of overdue tasks must not wake
any agent. The scheduler only sends pushes — the runner stays untouched.

Per-task dedupe is durable: `tasks.due_notified_at` is stamped after the
first fire. `update_task` clears it whenever `due_at` changes, so a
rescheduled task fires again at the new deadline.

`_tick` is factored out from the loop so tests can drive a single pass
deterministically.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.datetime_utils import utc_now
from app.db import SessionLocal
from app.notifications import service as notify_service
from app.tasks.models import Task

logger = logging.getLogger(__name__)

TICK_INTERVAL_SECONDS = 30.0


async def _tick(db: Session) -> int:
    """One pass over overdue, un-notified tasks. Returns count of fires."""
    now = utc_now()
    rows = list(
        db.scalars(
            select(Task).where(
                Task.due_at.is_not(None),
                Task.due_at <= now,
                Task.is_done.is_(False),
                Task.due_notified_at.is_(None),
            )
        )
    )
    fired = 0
    for task in rows:
        await notify_service.notify(
            event_type="task_due",
            title="Task due",
            body=task.title,
            url=f"/tasks/{task.id}",
            tag=f"task_due:{task.id}",
        )
        task.due_notified_at = now
        fired += 1
    if fired:
        db.commit()
    return fired


async def _loop() -> None:
    logger.info(
        "notifications: due-date scheduler starting (interval=%.1fs)",
        TICK_INTERVAL_SECONDS,
    )
    while True:
        try:
            await asyncio.sleep(TICK_INTERVAL_SECONDS)
            with SessionLocal() as db:
                await _tick(db)
        except asyncio.CancelledError:
            logger.info("notifications: due-date scheduler cancelled")
            raise
        except Exception:
            logger.exception("notifications: due-date scheduler tick failed; continuing")


_loop_task: asyncio.Task[None] | None = None


def start() -> None:
    """Spawn the scheduler on the running loop. Idempotent."""
    global _loop_task
    if _loop_task is not None and not _loop_task.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("notifications: cannot start due-date scheduler — no running loop")
        return
    _loop_task = loop.create_task(_loop())


def stop() -> None:
    global _loop_task
    if _loop_task is None:
        return
    _loop_task.cancel()
    _loop_task = None
