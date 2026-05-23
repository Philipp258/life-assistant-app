# ruff: noqa: F401
"""Runner package: per-session turn execution and the watchdog loop.

This package was split out of a single ``runner.py``. Public callers
still ``from app.chat import runner`` and reach attributes like
``runner.schedule_wake`` / ``runner.wake_session`` exactly as before;
the names are re-exported here.

Tests historically monkeypatch attributes on this package
(``monkeypatch.setattr(runner, "schedule_wake", ...)``) and expect the
patch to also affect *internal* runner call sites. Because those
internal calls now live in submodules with their own ``__dict__``, a
plain re-export here would silently break that behavior. To preserve
it, the module installs a ``__setattr__`` hook that propagates writes of
a known set of names down into the submodules that host the live
binding (see ``_PROPAGATE_TO``). ``_main_loop`` is read dynamically via
``__getattr__`` so that ``set_main_loop`` is visible through the
package without requiring callers to know which submodule owns it.
"""

from __future__ import annotations

import asyncio  # re-exported so tests can patch `runner.asyncio.sleep`.
import sys
from types import ModuleType
from typing_extensions import override

from app.chat.service import save_new_messages
from app.db import SessionLocal

from . import claims as _claims
from . import inputs as _inputs
from . import messages as _messages
from . import outcomes as _outcomes
from . import state as _state
from . import turn as _turn
from . import wake as _wake
from . import watchdog as _watchdog
from .claims import (
    _get_task_for_session,
    _task_in_terminal_state,
    list_in_flight_tasks,
    should_start_task,
)
from .messages import (
    ERROR_ESCALATION_THRESHOLD,
    ERROR_PAUSE_TASK_CHAT_TEMPLATE,
    ERROR_RETRY_TEMPLATE,
    ESCALATION_MESSAGE,
    MAIN_ERROR_TEMPLATE,
    RESCHEDULE_ESCALATION_THRESHOLD,
    RESCHEDULE_PAUSE_TASK_CHAT_TEMPLATE,
    STALL_ESCALATION_THRESHOLD,
    STALL_REMINDER_TEXT,
    RunResult,
    WakeOutcome,
    _build_stall_reminder,
    _sanitize_error_text,
    _StaleTaskInputRestart,
)
from .outcomes import (
    _handle_error_outcome,
    _handle_reschedule_limit_outcome,
    _persist_wake_outcome,
)
from .state import (
    _active_sessions,
    _last_wake_at,
    _pending_voice,
    _reap_session_state,
    _session_locks,
    _SESSION_STATE_TTL_SECONDS,
    _track_active,
    list_active_sessions,
    set_main_loop,
    set_pending_voice,
)
from .turn import run_session_turn
from .wake import (
    _wake_logged,
    schedule_wake,
    wake_main_for_terminal,
    wake_session,
)
from .watchdog import (
    WATCHDOG_BASE_GAP_SECONDS,
    WATCHDOG_INTERVAL_SECONDS,
    WATCHDOG_MAX_GAP_SECONDS,
    _gap_for,
    _watchdog_loop,
    start_watchdog,
    stop_watchdog,
)

__all__ = [
    "ERROR_ESCALATION_THRESHOLD",
    "ERROR_PAUSE_TASK_CHAT_TEMPLATE",
    "ERROR_RETRY_TEMPLATE",
    "ESCALATION_MESSAGE",
    "MAIN_ERROR_TEMPLATE",
    "RESCHEDULE_ESCALATION_THRESHOLD",
    "RESCHEDULE_PAUSE_TASK_CHAT_TEMPLATE",
    "RunResult",
    "STALL_ESCALATION_THRESHOLD",
    "STALL_REMINDER_TEXT",
    "WATCHDOG_BASE_GAP_SECONDS",
    "WATCHDOG_INTERVAL_SECONDS",
    "WATCHDOG_MAX_GAP_SECONDS",
    "WakeOutcome",
    "list_active_sessions",
    "list_in_flight_tasks",
    "run_session_turn",
    "save_new_messages",
    "schedule_wake",
    "set_main_loop",
    "set_pending_voice",
    "should_start_task",
    "start_watchdog",
    "stop_watchdog",
    "wake_main_for_terminal",
    "wake_session",
]


# Names whose runtime binding lives on a submodule. When tests
# monkeypatch the package-level attribute, the same value must be
# pushed onto the submodule's __dict__ so internal callers (which look
# up bare names in their own module globals) honor the patch. Listed
# explicitly to make the patch surface obvious — adding to this set is
# a deliberate API decision.
_PROPAGATE_TO: dict[str, tuple[ModuleType, ...]] = {
    "schedule_wake": (_wake,),
    "_wake_logged": (_wake, _watchdog),
    "wake_main_for_terminal": (_wake,),
    "run_session_turn": (_wake,),
    "_persist_wake_outcome": (_wake,),
    "save_new_messages": (_turn, _outcomes, _wake),
    "SessionLocal": (_claims, _outcomes, _turn, _wake, _watchdog),
    "_main_loop": (_state,),
}


class _RunnerPackage(ModuleType):
    @override
    def __setattr__(self, name: str, value: object) -> None:
        super().__setattr__(name, value)
        for sub in _PROPAGATE_TO.get(name, ()):
            setattr(sub, name, value)

    @override
    def __getattr__(self, name: str) -> object:
        if name == "_main_loop":
            return _state._main_loop
        raise AttributeError(name)


sys.modules[__name__].__class__ = _RunnerPackage
