"""Periodic safety-net loop.

Re-wakes eligible tasks whose normal `schedule_wake` never fired, and
re-pokes the main session when it still has undrained task-terminal
events. Per-task exponential backoff on consecutive errors keeps a
downed provider from being hammered at the base 60s cadence.
"""

from __future__ import annotations

import asyncio
import logging

from app.chat import events
from app.chat.service import get_or_create_main_session
from app.db import SessionLocal
from app.tasks.models import Task

from .claims import list_in_flight_tasks
from .state import (
    _active_sessions,
    _last_wake_at,
    _reap_session_state,
    _session_locks,
    consecutive_errors,
)
from .wake import _wake_logged

logger = logging.getLogger(__name__)


# Watchdog parameters. The watchdog is a safety net: if a normal
# `schedule_wake` ever fails to dispatch (e.g., a wake fired before the
# main loop was captured, or a transient exception), the watchdog
# eventually picks it up. To avoid a polling loop on tasks that have
# nothing left to do, we never re-wake a session within the gap returned
# by `_gap_for(task)`. Stalled tasks always re-fire on the base gap so
# the reminder lands quickly; errored tasks back off exponentially.
WATCHDOG_INTERVAL_SECONDS = 5.0
WATCHDOG_BASE_GAP_SECONDS = 60.0
WATCHDOG_MAX_GAP_SECONDS = 960.0  # 60 * 2**4


def _backoff_gap(consecutive_error_count: int) -> float:
    """Minimum re-wake gap, in seconds, for a given error streak.

    No errors → base 60s. Each consecutive error doubles the gap, capped
    at `WATCHDOG_MAX_GAP_SECONDS`.
    """
    if consecutive_error_count <= 0:
        return WATCHDOG_BASE_GAP_SECONDS
    return min(
        WATCHDOG_BASE_GAP_SECONDS * (2 ** min(consecutive_error_count, 4)),
        WATCHDOG_MAX_GAP_SECONDS,
    )


def _gap_for(task: Task) -> float:
    """Per-task minimum re-wake gap, in seconds.

    Stalls do not back off — the next tick after the base gap re-fires
    them with the reminder injected; only the error streak backs off.
    """
    return _backoff_gap(task.consecutive_errors)


async def _watchdog_loop() -> None:
    logger.info(
        "runner: watchdog starting (interval=%.1fs, base_gap=%.1fs, max_gap=%.1fs)",
        WATCHDOG_INTERVAL_SECONDS,
        WATCHDOG_BASE_GAP_SECONDS,
        WATCHDOG_MAX_GAP_SECONDS,
    )
    while True:
        try:
            await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)
            now = asyncio.get_running_loop().time()
            _reap_session_state(now)
            for task in list_in_flight_tasks():
                sid = task.chat_session_id
                if sid in _active_sessions:
                    continue
                lock = _session_locks[sid]
                if lock.locked():
                    continue
                last = _last_wake_at.get(sid)
                gap = _gap_for(task)
                if last is not None and (now - last) < gap:
                    continue
                if last is None:
                    logger.info("runner: watchdog waking unstarted session %d", sid)
                else:
                    logger.info(
                        "runner: watchdog re-waking session %d (gap=%.1fs, errors=%d)",
                        sid,
                        now - last,
                        task.consecutive_errors,
                    )
                asyncio.get_running_loop().create_task(_wake_logged(sid))

            # Kind-agnostic re-wake-until-drained: the singleton main
            # session is a consumer, not a task, so it never appears in
            # `list_in_flight_tasks`. Re-poke it on the base gap whenever
            # it still has undrained task-terminal events — the safety
            # net behind the post-terminal `wake_main_for_terminal` hop.
            with SessionLocal() as db:
                main_id = get_or_create_main_session(db).id
                undrained = events.has_undrained_events(db, main_id)
            if (
                undrained
                and main_id not in _active_sessions
                and not _session_locks[main_id].locked()
            ):
                last = _last_wake_at.get(main_id)
                # Back off the same way tasks do: a main wake that keeps
                # erroring against a downed provider must not be re-poked
                # every 60s (the 481-card incident). Streak is tracked in
                # `state._consecutive_errors` and reset on a clean wake.
                gap = _backoff_gap(consecutive_errors(main_id))
                if last is None or (now - last) >= gap:
                    logger.info("runner: watchdog waking main session %d (undrained)", main_id)
                    asyncio.get_running_loop().create_task(_wake_logged(main_id))
        except asyncio.CancelledError:
            logger.info("runner: watchdog cancelled")
            raise
        except Exception:
            logger.exception("runner: watchdog tick failed; continuing")


_watchdog_task: asyncio.Task[None] | None = None


def start_watchdog() -> None:
    """Spawn the watchdog on the running loop. Idempotent."""
    global _watchdog_task
    if _watchdog_task is not None and not _watchdog_task.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("runner: cannot start watchdog — no running loop")
        return
    _watchdog_task = loop.create_task(_watchdog_loop())


def stop_watchdog() -> None:
    global _watchdog_task
    if _watchdog_task is None:
        return
    _watchdog_task.cancel()
    _watchdog_task = None
