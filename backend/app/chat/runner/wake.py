"""`wake_session` + `schedule_wake`: the runner's public entry points.

Every external wake (user message, autonomous loop tick, terminal hop)
funnels through `schedule_wake` → `_wake_logged` → `wake_session`. The
per-session lock in `state._session_locks` serializes concurrent wakes
in this process; the `tasks.run_claimed_at` claim handles cross-process.
"""

from __future__ import annotations

import asyncio
import logging
import secrets

from pydantic_ai.messages import ModelResponse, TextPart

from app.chat import events, pubsub
from app.chat.service import force_compact_history, get_or_create_main_session, save_new_messages
from app.chat.session_policy import resolve_kind
from app.db import SessionLocal
from app.tasks.models import Task
from app.chat.models import ChatSession

from .claims import (
    _claim_task_run,
    _get_task_for_session,
    _release_task_run,
    _task_in_terminal_state,
    should_start_task,
)
from .inputs import _session_has_pending_user_input
from .messages import (
    MAIN_ERROR_TEMPLATE,
    RunResult,
    WakeOutcome,
    _is_context_window_error,
    _sanitize_error_text,
)
from .outcomes import _persist_wake_outcome
from .state import (
    _last_wake_at,
    _session_locks,
    _track_active,
    get_main_loop,
)
from .turn import run_session_turn
from .messages import _StaleTaskInputRestart

logger = logging.getLogger(__name__)


def wake_main_for_terminal(task_session_id: int) -> None:
    """Schedule a main-session wake after a task hit a terminal state.

    The terminal task tools / escalations have already recorded the
    hidden handoff; the main wake drains it as a task-terminal event
    (`app.chat.events`) and the main agent decides what to do. Split out
    as a seam so unit tests can stub the cross-session hop.
    """
    with SessionLocal() as db:
        main_id = get_or_create_main_session(db).id
    if main_id == task_session_id:
        return
    schedule_wake(main_id)


async def wake_session(session_id: int) -> RunResult:
    """Check eligibility and run one agent turn. Idempotent under
    concurrent wakes; serializes with the router on `_session_locks`.

    Task sessions gate on assignee/done/`do_at`. The main session gates
    on having undrained task-terminal events — a main wake exists only to
    surface task work, so an empty drain is a cheap no-op.
    """
    lock = _session_locks[session_id]
    async with lock:
        with SessionLocal() as db:
            chat = db.get(ChatSession, session_id)
        kind = resolve_kind(chat)

        # runner_started/runner_finished bracket ONLY a wake that
        # actually runs a turn (published inside the `outcome is None`
        # block). A no-op wake (watchdog tick, a message into a
        # done/blocked task) emits nothing — pubsub stays clean and the
        # WS client's stream isn't churned by unrelated wakes. Every
        # event of one running wake carries the same run_id so the
        # client can latch its turn and ignore a peer wake.
        run_id = secrets.token_hex(8)
        outcome: WakeOutcome | None = None
        count = 0
        claimed_task_id: int | None = None
        try:
            task_id: int | None = None
            if kind == "task":
                task = _get_task_for_session(session_id)
                if task is None:
                    outcome = "no_task"
                elif task.is_done:
                    outcome = "already_done"
                elif task.assignee != "assistant":
                    # Turn-based: a blocked / user-assigned task runs
                    # exactly ONE agent turn per user reply (NOT the
                    # autonomous loop, which the watchdog drives only for
                    # assignee='assistant'). No pending user message →
                    # nothing to do.
                    with SessionLocal() as db:
                        pending = _session_has_pending_user_input(db, session_id)
                    if pending:
                        task_id = task.id
                    else:
                        outcome = "paused"
                elif not should_start_task(task):
                    outcome = "scheduled"
                else:
                    task_id = task.id
            else:
                if chat is None:
                    outcome = "no_task"
                else:
                    with SessionLocal() as db:
                        run_main = events.has_undrained_events(
                            db, session_id
                        ) or _session_has_pending_user_input(db, session_id)
                    if not run_main:
                        outcome = "no_events"

            if outcome is None:
                pubsub.publish(
                    session_id,
                    {
                        "type": "runner_started",
                        "session_id": session_id,
                        "run_id": run_id,
                    },
                )
                if kind == "task" and task_id is not None:
                    # Claim the task across processes for the duration of
                    # this wake (released in the finally). The asyncio
                    # lock already serializes same-process wakes; this
                    # stops a restarted process's recovery from running
                    # a task this process is still executing.
                    _claim_task_run(task_id)
                    claimed_task_id = task_id
                errored = False
                error_text: str | None = None
                stale_restart = False
                try:
                    with _track_active(session_id):
                        count = await run_session_turn(session_id, run_id)
                except _StaleTaskInputRestart as restart:
                    stale_restart = True
                    count = restart.new_message_count
                except Exception as exc:
                    if kind == "task" and task_id is not None and _is_context_window_error(exc):
                        logger.warning(
                            "runner: context-window error for task session %d; "
                            "compacting and retrying once",
                            session_id,
                            exc_info=True,
                        )
                        try:
                            compacted = await force_compact_history(session_id)
                            if not compacted:
                                raise RuntimeError(
                                    "context window exceeded, and no task-chat history "
                                    "could be compacted; check recent tool return sizes"
                                ) from exc
                            with _track_active(session_id):
                                count = await run_session_turn(session_id, run_id)
                        except _StaleTaskInputRestart as restart:
                            stale_restart = True
                            count = restart.new_message_count
                        except Exception as retry_exc:
                            errored = True
                            error_text = _sanitize_error_text(retry_exc)
                            logger.exception(
                                "runner: context-window retry for session %d failed",
                                session_id,
                            )
                    else:
                        errored = True
                        error_text = _sanitize_error_text(exc)
                        logger.exception("runner: wake for session %d failed", session_id)

                _last_wake_at[session_id] = asyncio.get_running_loop().time()

                if kind == "task":
                    assert task_id is not None
                    if stale_restart:
                        outcome = "restarted"
                        schedule_wake(session_id)
                    else:
                        outcome = _persist_wake_outcome(
                            task_id, errored=errored, error_text=error_text
                        )
                    # Surface to main only on a real terminal transition
                    # (complete/reassign/reschedule or a runner
                    # escalation). A turn-based reply to a user-assigned
                    # task records no handoff, so the main wake drains
                    # nothing and no-ops — harmless.
                    with SessionLocal() as db:
                        task_after = db.get(Task, task_id)
                    if task_after is not None and _task_in_terminal_state(task_after):
                        try:
                            wake_main_for_terminal(session_id)
                        except Exception:
                            logger.exception(
                                "runner: main wake for terminal task session %d failed",
                                session_id,
                            )
                else:
                    outcome = "errored" if errored else "completed"
                    if not errored:
                        # A task that terminated *during* this main turn
                        # recorded a fresh handoff the drain hasn't seen;
                        # re-wake until the cursor catches up.
                        with SessionLocal() as db:
                            if events.has_undrained_events(db, session_id):
                                schedule_wake(session_id)
                    else:
                        # Surface the failure to the user instead of
                        # silently losing the turn. Auto-retry would risk
                        # a hot loop against a downed provider (the same
                        # reasoning as the task error path); a single
                        # visible message lets the user retry. Their next
                        # message drives a fresh turn normally.
                        body = MAIN_ERROR_TEMPLATE.format(
                            error=error_text or "unknown error",
                        )
                        try:
                            with SessionLocal() as db:
                                save_new_messages(
                                    db,
                                    session_id,
                                    [ModelResponse(parts=[TextPart(content=body)])],
                                )
                        except Exception:
                            logger.exception(
                                "runner: failed to surface main-turn error for session %d",
                                session_id,
                            )

                # Close the client's stream for THIS turn (even on
                # error — the surfaced notice / partial reply is
                # persisted; the spinner must stop).
                pubsub.publish(
                    session_id,
                    {
                        "type": "runner_finished",
                        "session_id": session_id,
                        "run_id": run_id,
                        "outcome": outcome,
                        "new_message_count": count,
                    },
                )

            return RunResult(outcome=outcome, new_message_count=count)
        finally:
            if claimed_task_id is not None:
                _release_task_run(claimed_task_id)


def schedule_wake(session_id: int) -> None:
    """Fire-and-forget: schedule a wake from any thread.

    - If called from inside the event loop (async route, lifespan), the
      wake is scheduled directly with `loop.create_task`.
    - If called from a worker thread (sync FastAPI route, pydantic-ai
      sync tool under `run_in_executor`), the wake is dispatched onto the
      captured main loop via `run_coroutine_threadsafe`.
    - If no main loop has been captured (unit tests using `asyncio.run`
      against `wake_session` directly), this is a no-op.
    """
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_wake_logged(session_id))
        logger.info("runner: scheduled wake (inline) for session %d", session_id)
        return
    except RuntimeError:
        pass

    main_loop = get_main_loop()
    if main_loop is None or main_loop.is_closed():
        logger.warning(
            "runner: no main loop captured, dropping wake for session %d "
            "— did app startup complete?",
            session_id,
        )
        return

    asyncio.run_coroutine_threadsafe(_wake_logged(session_id), main_loop)
    logger.info("runner: scheduled wake (cross-thread) for session %d", session_id)


async def _wake_logged(session_id: int) -> None:
    try:
        result = await wake_session(session_id)
        logger.info(
            "runner: session %d → %s (%d new messages)",
            session_id,
            result.outcome,
            result.new_message_count,
        )
    except Exception:
        logger.exception("runner: wake for session %d failed", session_id)
