"""Process-global mutable state for the runner.

The runner is single-process by design, so these in-memory maps are the
source of truth for lock ownership, active-wake tracking, and last-wake
timestamps. A periodic reaper (`_reap_session_state`) keeps the maps
from growing one entry per session id ever touched.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager


_session_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

# Captured at app startup so `schedule_wake` can dispatch wakes from
# non-loop threads (sync FastAPI handlers, pydantic-ai sync tools running
# under run_in_executor, etc.). Without this, wakes from those call sites
# silently dropped because `asyncio.get_running_loop()` raises in worker
# threads — meaning tasks created from chat or the New Task button never
# auto-started until a server restart re-ran the lifespan recovery.
_main_loop: asyncio.AbstractEventLoop | None = None

# Sessions for which a wake is currently executing. Surfaced via
# `list_active_sessions` so the UI can show a "live" indicator only on
# tasks whose runner is actually mid-turn.
_active_sessions: set[int] = set()

# Monotonic timestamp of the last wake that finished for each session.
# Used by the watchdog to avoid re-poking sessions we just ran.
_last_wake_at: dict[int, float] = {}

# Per-session one-shot voice-mode hint set by the WebSocket input handler
# (`app.chat.ws`) and consumed by the next `run_session_turn`. Voice is a
# property of a user-typed turn; autonomous wakes are never voice. Single
# process, so a plain dict popped at turn start is enough — no leak across
# turns, default False.
_pending_voice: dict[int, bool] = {}


# An idle session's lock/timestamp is dropped after this long with no
# wake, so the process-global maps don't grow one permanent entry per
# distinct session id ever touched.
_SESSION_STATE_TTL_SECONDS = 3600.0


def set_pending_voice(session_id: int, voice: bool) -> None:
    if voice:
        _pending_voice[session_id] = True
    else:
        _pending_voice.pop(session_id, None)


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _main_loop
    _main_loop = loop


def get_main_loop() -> asyncio.AbstractEventLoop | None:
    return _main_loop


@contextmanager
def _track_active(session_id: int) -> Iterator[None]:
    _active_sessions.add(session_id)
    try:
        yield
    finally:
        _active_sessions.discard(session_id)


def list_active_sessions() -> list[int]:
    return sorted(_active_sessions)


def _reap_session_state(now: float) -> None:
    """Drop process-global per-session state for long-idle sessions.

    Only entries that are demonstrably inactive — not currently
    running, lock free, last wake older than the TTL — are removed; a
    later wake simply recreates a fresh lock. Keeps `_session_locks` /
    `_last_wake_at` / `_pending_voice` from growing unbounded.
    """
    for sid, last in list(_last_wake_at.items()):
        if now - last < _SESSION_STATE_TTL_SECONDS:
            continue
        if sid in _active_sessions:
            continue
        lock = _session_locks.get(sid)
        if lock is not None and lock.locked():
            continue
        _last_wake_at.pop(sid, None)
        _pending_voice.pop(sid, None)
        _session_locks.pop(sid, None)
