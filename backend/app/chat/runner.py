"""One turn engine for task chats *and* the main chat.

`run_session_turn` is the only turn executor. It runs the agent once
against a session, persisting incrementally; the per-kind differences
(`app.chat.session_policy`) are which preamble the agent gets, whether
the session drains task-terminal events (`app.chat.events`), and whether
it is wake-eligible. EVERY turn — a user message (over the WebSocket,
`app.chat.ws`, which persists it then `schedule_wake`s), the autonomous
task loop, a terminal-triggered main wake, watchdog recovery — comes
through `wake_session` and serializes on the per-session lock
(`_session_locks`). There is no separate streaming HTTP path anymore.

## Assignee semantics

Task-bound chats behave differently depending on `task.assignee`:

- **`assignee = 'user'` — turn-based, like a normal chat.** Each user
  message triggers exactly one agent turn: `wake_session` runs a turn
  for a user-assigned task only when `_session_has_pending_user_input`
  (the newest row is an unanswered user message). The watchdog will
  not wake a user-assigned task. This is how the user "blocks" the
  agent: they own the next move.

- **`assignee = 'assistant'` — autonomous loop.** The watchdog
  (`_watchdog_loop` below) wakes the session repeatedly until the task
  is done or reassigned. Each wake is a single `agent.run`. The user
  may post messages at any time mid-loop; if that happens after the
  wake loaded history, the runner stops at the next safe graph-node
  boundary and schedules a fresh wake so the next `agent.run` reloads
  the corrected chat history.

`reassign_task` is the pause/resume mechanism. `reassign_task('user')`
ends the autonomous loop after the current turn finishes. The user
posting any message (or explicitly reassigning back) hands control
back to the agent.

## Wake mechanics

A "wake" is a single `agent.run` against a task-bound chat session. The
agent's own tool-call loop drives the work within that turn — it can
call any number of tools (`complete_task`, `reassign_task`,
`reschedule_task`, etc.) and only ends when it produces a final response
without further tool calls.

Every wake should end in one of three **terminal** states:
1. `is_done = True` — `complete_task` was called.
2. `assignee = "user"` — `reassign_task('user', ...)` was called.
3. `do_at > now` — `reschedule_task` was called.

Anything else after a clean `agent.run` return is a **soft stall** — the
agent finished its turn without ending the loop. The runner increments
`task.consecutive_stalls`; on the next wake `run_session_turn` injects
a reminder; once the streak hits `STALL_ESCALATION_THRESHOLD` we flip
the task to the user with an explanation message.

Repeated reschedules are valid for long-running task workflows, but still
bounded: each reschedule increments `task.consecutive_reschedules`, and
after `RESCHEDULE_ESCALATION_THRESHOLD` consecutive reschedules we pause
the task back to the user. Completing, reassigning, or user re-engagement
resets the streak.

If `agent.run` raises, the wake is a **hard error** — usually an LLM
provider outage. We increment `task.consecutive_errors` and append a
sanitized error message to the task chat so the failure is visible
where the work is happening; the watchdog applies exponential backoff
(`_gap_for`) per task so we don't hammer a downed provider at the
base 60s cadence. Once the streak hits `ERROR_ESCALATION_THRESHOLD`
we drop a final pause notice in the task chat and flip the task to
the user via `update_task` — recording a handoff exactly like the
stall escalation, so the main session surfaces it on its next drain.
Errors do *not* reset the stall streak; only a clean terminated wake
(or explicit re-engagement via assignee→assistant flip) resets either
counter.

A task wake exits without running anything if the task isn't
run-eligible (missing, done, or assigned to user — see `wake_session`
below). A *main* wake exits without running unless the main session has
undrained task-terminal events. Subsequent wakes are triggered by fresh
external events: user messages, assignment flips, or a task hitting a
terminal state.

After every task wake that lands the task in a terminal state (done,
flipped to user, or rescheduled into the future), the task has recorded
a hidden handoff (`save_task_handoff`) and we wake the singleton main
session (`wake_main_for_terminal`). The main wake runs the *same*
main-chat agent the user talks to — full toolset, real (compacted)
main-chat history — with the task-terminal events delivered as a
synthetic user-role report (`app.chat.events`). It decides
conversationally whether to message the user, relay an answer back into
the task, or stay quiet. There is no separate "handoff" agent. The
drain turn is run with the `do_nothing` output tool: a text reply
notifies the user like any other main-chat message; calling `do_nothing`
ends the turn silently — the event cursor still advances, but no row is
persisted and no push fires (the relevance/noise call is the model's).

Concurrency: an `asyncio.Lock` per session_id ensures we never run two
agent calls against the same chat at once — including a user-driven
main turn (router) racing an event-triggered main wake (here). This is
single-process; a real worker (arq, celery) is out of scope.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    PartDeltaEvent,
    PartStartEvent,
    SystemPromptPart,
    TextPart,
    TextPartDelta,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_graph.nodes import End
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.agent import build_system_prompt, get_agent
from app.agent.deps import AgentDeps
from app.agent.usage import default_usage_limits
from app.chat import events, pubsub
from app.chat.models import ChatSession, Message
from app.chat.repair import close_dangling_tool_calls, repair_persisted_history
from app.chat.service import (
    aload_compacted_history,
    create_streaming_response_row,
    get_or_create_main_session,
    load_session_history_with_cursor,
    publish_streaming_text_upsert,
    save_new_messages,
    update_streaming_response_row,
)
from app.chat.session_policy import resolve_kind
from app.datetime_utils import normalize_to_naive_utc, utc_now
from app.db import SessionLocal
from app.tasks.models import Task

logger = logging.getLogger(__name__)


WakeOutcome = Literal[
    "terminated",
    "stalled",
    "errored",
    "no_task",
    "already_done",
    "paused",
    "scheduled",
    "restarted",
    "completed",  # a main wake ran a turn
    "no_events",  # a main wake found nothing to drain
]


@dataclass
class RunResult:
    outcome: WakeOutcome
    new_message_count: int = 0


class _StaleTaskInputRestart(Exception):
    """Internal non-error signal: restart the task wake with fresh chat history."""

    def __init__(self, new_message_count: int) -> None:
        super().__init__("task input changed during runner loop")
        self.new_message_count = new_message_count


# Streak at which we stop trusting the agent to converge on its own and
# flip the task back to the user with an explanatory message.
STALL_ESCALATION_THRESHOLD = 3

# Streak at which we stop retrying a task whose wakes keep raising and
# hand it back to the user. Mirrors STALL_ESCALATION_THRESHOLD; the
# watchdog backoff (`_gap_for`) handles the first two.
ERROR_ESCALATION_THRESHOLD = 3

# Streak at which a task that keeps deferring itself is treated as an
# infinite reschedule loop. High enough for long implementation-agent
# workflows that legitimately poll/check back many times.
RESCHEDULE_ESCALATION_THRESHOLD = 50

# A `tasks.run_claimed_at` newer than this means a runner is actively
# mid-wake on the task; another runner (e.g. a freshly-restarted
# process's lifespan recovery) must not also run it. Generous so a long
# tool-heavy turn never looks stale to a peer; if a runner dies the
# claim goes stale after this and the watchdog reclaims the task.
RUN_CLAIM_TTL_SECONDS = 1800.0

STALL_REMINDER_TEXT = (
    "[runner reminder] Your previous turn finished without ending the task. "
    "End this wake with the terminal task move that matches reality: "
    "`complete_task(handoff=...)`, `reassign_task(assignee='user', handoff=...)`, "
    "or `reschedule_task(do_at=..., handoff=...)`. The handoff is hidden "
    "context for the main-chat assistant, not a direct user message."
)

ESCALATION_MESSAGE = (
    "{assistant_name} tried this task three times in a row without converging on "
    "complete, reassign, or reschedule. Handing it back to you so we "
    "don't loop. Reply in main chat or in the task chat when you'd like "
    "another attempt; if you reply in main chat, the assistant can relay the "
    "instruction back into this task."
)

ERROR_RETRY_TEMPLATE = (
    "{assistant_name} hit an error while running this task. I'll retry automatically "
    "with backoff.\n\nError: `{error}`"
)

# Main chat has no autonomous retry loop; on a failed turn we surface
# the error once so the user can simply send again (vs. silently
# losing the turn).
MAIN_ERROR_TEMPLATE = (
    "Something went wrong handling that — your message wasn't answered. "
    "Please try again.\n\nError: `{error}`"
)

ERROR_PAUSE_TASK_CHAT_TEMPLATE = (
    "{assistant_name} hit errors {count} times in a row while running this task, so "
    "I'm pausing it instead of retrying forever. Reply in main chat or "
    "in this task after the underlying problem is fixed.\n\nLast error: `{error}`"
)

RESCHEDULE_PAUSE_TASK_CHAT_TEMPLATE = (
    "{assistant_name} rescheduled this task {count} times in a row, so I'm pausing it "
    "instead of deferring forever. Reply in main chat or in this task when you'd like "
    "another attempt."
)

TERMINAL_TASK_TOOL_NAMES = {
    "ask_user_choice",
    "complete_task",
    "reassign_task",
    "reschedule_task",
}


def _sanitize_error_text(exc: BaseException, *, max_len: int = 200) -> str:
    """Concise one-line representation of an exception for chat surfaces.

    Stack traces stay in the logger; users only see `Type: message` so
    the chat doesn't get clobbered with internals. Newlines are
    collapsed to keep the rendered card single-paragraph.
    """
    msg = str(exc).strip().splitlines()
    head = msg[0] if msg else ""
    summary = f"{type(exc).__name__}: {head}" if head else type(exc).__name__
    if len(summary) > max_len:
        summary = summary[: max_len - 1].rstrip() + "…"
    return summary


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


def set_pending_voice(session_id: int, voice: bool) -> None:
    if voice:
        _pending_voice[session_id] = True
    else:
        _pending_voice.pop(session_id, None)


# An idle session's lock/timestamp is dropped after this long with no
# wake, so the process-global maps don't grow one permanent entry per
# distinct session id ever touched.
_SESSION_STATE_TTL_SECONDS = 3600.0


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


def _session_has_pending_user_input(db: Session, session_id: int) -> bool:
    """Whether the newest visible row is an unanswered user message.

    User input arrives over the channel as a persisted user
    `ModelRequest` + a `schedule_wake`; this predicate lets that wake
    actually run a turn — for the main session, and for a task chat in
    turn-based mode (assignee='user': the user replied to a blocked
    task and expects exactly one agent turn). It closes as soon as the
    agent's reply (a response row) or a tool-return request lands on
    top, so it cannot hot-loop.
    """
    row = db.scalars(
        select(Message)
        .where(Message.session_id == session_id, Message.archived_at.is_(None))
        .order_by(Message.id.desc())
        .limit(1)
    ).first()
    if row is None or row.kind != "request":
        return False
    raw: dict[str, Any] = row.parts_json if isinstance(row.parts_json, dict) else {}
    for part in raw.get("parts", []) or []:
        if isinstance(part, dict) and (
            part.get("part_kind") == "user-prompt" or part.get("kind") == "user-prompt"
        ):
            return True
    return False


def _is_user_or_relay_input_row(row: Message) -> bool:
    """Rows that should refresh an autonomous task's chat context."""
    if row.source_session_id is not None:
        return True
    if row.kind != "request":
        return False
    raw: dict[str, Any] = row.parts_json if isinstance(row.parts_json, dict) else {}
    for part in raw.get("parts", []) or []:
        if isinstance(part, dict) and (
            part.get("part_kind") == "user-prompt" or part.get("kind") == "user-prompt"
        ):
            return True
    return False


def _has_new_task_input_since(db: Session, session_id: int, after_id: int) -> bool:
    rows = db.scalars(
        select(Message)
        .where(
            Message.session_id == session_id,
            Message.archived_at.is_(None),
            Message.id > after_id,
        )
        .order_by(Message.id.asc())
    ).all()
    return any(_is_user_or_relay_input_row(row) for row in rows)


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _main_loop
    _main_loop = loop


@contextmanager
def _track_active(session_id: int) -> Iterator[None]:
    _active_sessions.add(session_id)
    try:
        yield
    finally:
        _active_sessions.discard(session_id)


def list_active_sessions() -> list[int]:
    return sorted(_active_sessions)


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


def _bootstrap_prompt(task: Task) -> str:
    """Synthetic user prompt sent on the first wake of a freshly created task.

    Most chat models (including Z.AI's glm-* family) reject requests that
    have only a system message and no user content. When the task chat is
    empty, we inject a user prompt built from the task's title and
    description so the agent has something concrete to respond to. The
    saved history then contains the bootstrap prompt + the agent's reply,
    and subsequent wakes can run normally.
    """
    parts = [
        f"Begin task #{task.id}: {task.title}",
    ]
    if task.description and task.description.strip():
        parts.append(f"Notes: {task.description.strip()}")
    parts.append(
        "Work in this task chat. Share useful progress here, not by editing "
        "the task description. When done, blocked on the user, or waiting on "
        "time, use the matching terminal task tool with a handoff for the "
        "main-chat assistant. The terminal tools operate on this chat's task "
        "implicitly and do not post directly to main chat."
    )
    return "\n\n".join(parts)


def _build_stall_reminder() -> ModelRequest:
    """Synthetic system-prompt request used to nudge a stalled agent.

    A `ModelRequest` carrying a single `SystemPromptPart`. Not
    persisted — injected per wake when `task.consecutive_stalls > 0`.
    """
    return ModelRequest(parts=[SystemPromptPart(content=STALL_REMINDER_TEXT)])


async def run_session_turn(session_id: int, run_id: str = "") -> int:
    """Run one agent call against the session, persisting incrementally.

    Returns the number of new messages persisted by this wake.

    Uses `agent.iter()` and flushes new messages to the DB after every
    graph node so that user-visible progress (assistant text, tool calls,
    tool results) survives errors, cancellations, and process restarts
    mid-turn. The DB is the source of truth — if the wake errors after
    some tool calls have already happened, those rows remain and the
    error notice from `_handle_error_outcome` lands after them.

    Idempotency: persistence advances a `persisted_count` cursor against
    `agent_run.new_messages()`, so we only ever append the suffix we
    haven't saved yet — re-running the same wake (after an external
    retry) starts from a fresh `agent.iter()` against the now-persisted
    history.

    Per-kind (`app.chat.session_policy`): the main session reads its
    compacted history and drains task-terminal events
    (`app.chat.events`) appended at the end as a synthetic user-role
    report; a task chat reads its full history with no event drain.
    """
    with SessionLocal() as db:
        # Heal any dangling tool calls from a previously interrupted turn
        # before loading history. Without this, an aborted mid-tool wake
        # would leave the last response carrying open tool_call_ids and
        # the next provider request would be rejected.
        repair_persisted_history(db, session_id)
        chat = db.get(ChatSession, session_id)
        kind = resolve_kind(chat)
        task = _get_task_for_session(session_id)

    seen: list[Message] = []
    injected: list[ModelMessage] = []
    task_history_cursor: int = 0
    if kind == "main":
        # Awaiting `aload_compacted_history` inside the open session is
        # the established pattern (DB calls stay sync; only the optional
        # summarizer LLM round trip is awaited). Drain terminal events in
        # the same session so the cursor read is consistent.
        with SessionLocal() as db:
            own_history = await aload_compacted_history(db, session_id)
            injected, seen = events.drain_terminal_events(db, session_id)
    else:
        with SessionLocal() as db:
            own_history, task_history_cursor = load_session_history_with_cursor(db, session_id)

    history: list[ModelMessage] = list(own_history)
    if task is not None and task.consecutive_stalls > 0:
        # Append after own_history so the reminder is the most recent
        # context the model sees. Strict copy: list the three terminal
        # options, no narration permitted.
        history = history + [_build_stall_reminder()]

    if not own_history and task is not None:
        # Empty task chat: persist the synthetic bootstrap prompt *before*
        # the model call. Newly-created assistant tasks then have visible
        # activity in their chat as soon as the runner starts, rather than
        # staying blank until the first full agent turn completes. Running
        # the agent from message_history avoids saving the prompt twice.
        bootstrap = ModelRequest(
            parts=[UserPromptPart(content=_bootstrap_prompt(task), timestamp=utc_now())]
        )
        with SessionLocal() as db:
            rows = save_new_messages(db, session_id, [bootstrap])
            task_history_cursor = max(task_history_cursor, *(row.id for row in rows))
        history = history + [bootstrap]

    # Task-terminal events (main only) ride at the END as a synthetic
    # user-role report. Ending on a user turn keeps an autonomous main
    # wake (no real user message) a valid request and a clear triage
    # target; the model replies or calls `do_nothing` (silence).
    history = history + injected

    agent = get_agent()
    voice = _pending_voice.pop(session_id, False)

    # pydantic-ai only auto-adds `@agent.system_prompt` for the very
    # first request of a fresh run; with `message_history` set (always,
    # here) it would call the model with NO system prompt — wrong
    # identity, no memory/tools guidance, no voice marker. The deleted
    # POST path got this from the Vercel adapter's system-prompt
    # reinjection. Mirror it by prepending a freshly built prompt. We do
    # NOT strip existing SystemPromptParts: the stall reminder and task
    # handoffs are deliberately SystemPromptPart-only ModelRequests and
    # must survive (a capability with `replace_existing` would eat them
    # and break the "history ends with a ModelRequest" invariant).
    history = [
        ModelRequest(
            parts=[SystemPromptPart(content=build_system_prompt(session_id, voice_mode=voice))]
        )
    ] + history

    persisted_count = 0
    streamed_response_row_ids: list[int] = []
    # Event-drain turns (the main session surfacing a task handoff)
    # DEFER all persistence to one final transaction that also advances
    # the event cursor — see the atomic block after the agent loop. The
    # reply and the cursor must commit together, or a process exit
    # between them re-drains the handoff and the model answers it twice
    # (the duplicate-surfacing bug). Non-event turns keep incremental
    # flushing for mid-turn crash-safety of tool progress.
    defer_persist = bool(seen)

    def _flush(messages_so_far: list[ModelMessage]) -> None:
        nonlocal persisted_count
        if defer_persist:
            return
        pending = messages_so_far[persisted_count:]
        if not pending:
            return
        to_save: list[ModelMessage] = []

        def flush_buffer() -> None:
            nonlocal persisted_count, to_save
            if not to_save:
                return
            with SessionLocal() as db:
                save_new_messages(db, session_id, to_save)
            persisted_count += len(to_save)
            to_save = []

        for message in pending:
            if isinstance(message, ModelResponse) and streamed_response_row_ids:
                flush_buffer()
                row_id = streamed_response_row_ids.pop(0)
                with SessionLocal() as db:
                    update_streaming_response_row(
                        db,
                        row_id,
                        message,
                        run_id=run_id,
                    )
                persisted_count += 1
            else:
                to_save.append(message)
        flush_buffer()

    async def _stream_text(node: object) -> None:
        """Forward token-level assistant text to the session's channel.

        Best-effort live UX only — the authoritative content is the
        persisted snapshot pushed by `_flush`. We reset per model-request
        node so a post-tool continuation streams as its own draft.
        """
        buf: dict[int, str] = {}
        streamed_row_id: int | None = None
        pubsub.publish(
            session_id,
            {"type": "message_start", "session_id": session_id, "run_id": run_id},
        )
        async with node.stream(agent_run.ctx) as request_stream:  # type: ignore[attr-defined]
            async for event in request_stream:
                if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
                    buf[event.index] = event.part.content or ""
                elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
                    buf[event.index] = buf.get(event.index, "") + event.delta.content_delta
                else:
                    continue
                text = "".join(buf[i] for i in sorted(buf))
                if text:
                    if not defer_persist:
                        if streamed_row_id is None:
                            with SessionLocal() as db:
                                row = create_streaming_response_row(db, session_id, text)
                            streamed_row_id = row.id
                            streamed_response_row_ids.append(streamed_row_id)
                        publish_streaming_text_upsert(
                            session_id,
                            streamed_row_id,
                            text,
                            run_id=run_id,
                        )
                    else:
                        pubsub.publish(
                            session_id,
                            {
                                "type": "part_delta",
                                "session_id": session_id,
                                "text": text,
                                "run_id": run_id,
                            },
                        )

    iter_kwargs: dict[str, Any] = dict(
        message_history=history,
        deps=AgentDeps(session_id=session_id, voice_mode=voice),
        usage_limits=default_usage_limits(),
    )
    if seen:
        # Drain turns only: offer the terminating `do_nothing` output
        # tool. Calling it ends the run (pydantic-ai output-tool
        # semantics) with `result.output` a `StaySilent` — the silence
        # signal is explicit and framework-guaranteed, not a blank-text
        # heuristic. Normal chat turns keep the default `str` output.
        iter_kwargs["output_type"] = [str, events.SILENCE_OUTPUT]
    restart_for_stale_input = False

    def _stale_task_input_waiting() -> bool:
        if kind != "task":
            return False
        with SessionLocal() as db:
            return _has_new_task_input_since(db, session_id, task_history_cursor)

    def _stop_for_stale_task_input(node: object) -> bool:
        if isinstance(node, End) or not _stale_task_input_waiting():
            return False
        # Stop before another model/tool step runs on stale task-chat
        # context. If the completed node ended with tool calls, persist
        # synthetic returns so the fresh wake has provider-valid history.
        closed = close_dangling_tool_calls(list(agent_run.new_messages()))
        _flush(closed)
        logger.info(
            "runner: restarting session %d after fresh task-chat input",
            session_id,
        )
        return True

    def _pending_tool_return_request(node: object) -> ModelRequest | None:
        request = getattr(node, "request", None)
        if not isinstance(request, ModelRequest):
            return None
        if not any(isinstance(part, ToolReturnPart) for part in request.parts):
            return None
        return request

    def _messages_with_pending_tool_returns(
        node: object, messages: list[ModelMessage]
    ) -> list[ModelMessage]:
        request = _pending_tool_return_request(node)
        if request is None or request in messages:
            return messages
        return messages + [request]

    def _flush_pending_tool_return_request(node: object, messages: list[ModelMessage]) -> None:
        request = _pending_tool_return_request(node)
        if request is not None and request not in messages:
            _flush(messages + [request])

    async with agent.iter(**iter_kwargs) as agent_run:
        final_messages: list[ModelMessage] = []
        try:
            async for node in agent_run:
                messages = list(agent_run.new_messages())
                _flush(messages)
                if _stop_for_stale_task_input(node):
                    restart_for_stale_input = True
                    break
                boundary_messages = _messages_with_pending_tool_returns(node, messages)
                if kind == "task" and _stop_after_terminal_task_boundary(
                    task.id if task else None,
                    messages=boundary_messages,
                ):
                    _flush_pending_tool_return_request(node, messages)
                    break
                if Agent.is_model_request_node(node):
                    await _stream_text(node)
                messages = list(agent_run.new_messages())
                _flush(messages)
                if _stop_for_stale_task_input(node):
                    restart_for_stale_input = True
                    break
                boundary_messages = _messages_with_pending_tool_returns(node, messages)
                if kind == "task" and _stop_after_terminal_task_boundary(
                    task.id if task else None,
                    messages=boundary_messages,
                ):
                    _flush_pending_tool_return_request(node, messages)
                    break
            final_messages = list(agent_run.new_messages())
        except BaseException:
            # Persist whatever the agent managed to produce before
            # bailing. Pair any dangling tool calls with synthetic
            # "interrupted" returns so the next wake's history loads
            # cleanly (most providers reject a trailing assistant turn
            # that has unresolved tool_call_ids).
            try:
                accumulated = list(agent_run.new_messages())
                closed = close_dangling_tool_calls(accumulated)
                _flush(closed)
            except Exception:
                logger.exception(
                    "runner: failed to persist partial progress for session %d",
                    session_id,
                )
            raise

    if restart_for_stale_input:
        raise _StaleTaskInputRestart(persisted_count)

    if seen:
        # Atomic: persist the turn's reply AND advance the event cursor
        # in ONE transaction. Either both land or neither — so a crash /
        # reload / deploy mid-turn can never leave the reply persisted
        # with the handoff un-cursored (which made the model re-answer
        # it on the next wake).
        run_result = agent_run.result
        silent = run_result is not None and isinstance(run_result.output, events.StaySilent)
        with SessionLocal() as db:
            events.advance_event_cursor(db, session_id, seen=seen, commit=False)
            # Silence: drop the whole turn (the `do_nothing` output
            # tool-call/return pair, no real reply) — cursor-only commit,
            # no visible row, no push. Accepted edge: if the model relays
            # to a task AND then stays silent, the relay tool messages are
            # dropped from main history too. The relay side effect already
            # ran and the resumed task re-handoffs later, so this only
            # costs a history breadcrumb — not correctness.
            pending: list[ModelMessage] = [] if silent else list(final_messages[persisted_count:])
            if pending:
                # save_new_messages commits — flushing the staged cursor
                # change on the same session in the same transaction.
                save_new_messages(db, session_id, pending)
                persisted_count += len(pending)
            else:
                db.commit()

    return persisted_count


def _persist_wake_outcome(
    task_id: int,
    *,
    errored: bool = False,
    error_text: str | None = None,
) -> WakeOutcome:
    """Classify a finished wake and persist counter changes.

    Called once per task wake from `wake_session`. Reloads the task in a
    fresh session so we see any field mutations the agent made via tools
    (e.g. `complete_task` flipping `is_done`, `reschedule_task` setting
    `do_at`). When the stall streak crosses the escalation threshold,
    flips the task to `assignee="user"` via `update_task` and drops the
    explanation message into the task chat (the user sees it where the
    work happened) plus a hidden handoff the main session drains next.

    On hard errors, appends a sanitized error message to the task chat
    so the user sees the failure where the work happens. After
    `ERROR_ESCALATION_THRESHOLD` consecutive errors the task is also
    handed back to the user with a final pause notice in the task chat;
    main-chat surfacing rides the same task-terminal event drain.
    """
    now = utc_now()
    with SessionLocal() as session:
        task = session.get(Task, task_id)
        if task is None:
            return "no_task"

        if errored:
            task.consecutive_errors += 1
            outcome: WakeOutcome = "errored"
        elif task.is_done or task.assignee == "user":
            task.consecutive_stalls = 0
            task.consecutive_errors = 0
            task.consecutive_reschedules = 0
            outcome = "terminated"
        elif task.do_at is not None and normalize_to_naive_utc(task.do_at) > now:
            task.consecutive_stalls = 0
            task.consecutive_errors = 0
            task.consecutive_reschedules += 1
            outcome = "terminated"
        else:
            task.consecutive_stalls += 1
            outcome = "stalled"
        session.commit()

        if outcome == "errored":
            _handle_error_outcome(session, task_id, error_text or "")

        if (
            outcome == "terminated"
            and task.assignee == "assistant"
            and not task.is_done
            and task.do_at is not None
            and normalize_to_naive_utc(task.do_at) > now
            and task.consecutive_reschedules >= RESCHEDULE_ESCALATION_THRESHOLD
        ):
            _handle_reschedule_limit_outcome(session, task_id)

        if outcome == "stalled" and task.consecutive_stalls >= STALL_ESCALATION_THRESHOLD:
            from app.tasks.schemas import TaskUpdate
            from app.tasks.service import update_task

            logger.warning(
                "runner: escalating task %d to user after %d consecutive stalls",
                task_id,
                task.consecutive_stalls,
            )
            chat_session_id = task.chat_session_id
            if chat_session_id is not None:
                from app.knowledge.identity import resolve_assistant_name

                body = ESCALATION_MESSAGE.format(assistant_name=resolve_assistant_name())
                save_new_messages(
                    session,
                    chat_session_id,
                    [ModelResponse(parts=[TextPart(content=body)])],
                )
                from app.chat.service import save_task_handoff

                save_task_handoff(session, chat_session_id, body)
            update_task(session, task_id, TaskUpdate(assignee="user"))
    return outcome


def _handle_reschedule_limit_outcome(session: Session, task_id: int) -> None:
    from app.knowledge.identity import resolve_assistant_name
    from app.tasks.schemas import TaskUpdate
    from app.tasks.service import update_task

    task = session.get(Task, task_id)
    if task is None or task.chat_session_id is None:
        return

    body = RESCHEDULE_PAUSE_TASK_CHAT_TEMPLATE.format(
        assistant_name=resolve_assistant_name(),
        count=task.consecutive_reschedules,
    )
    save_new_messages(
        session,
        task.chat_session_id,
        [ModelResponse(parts=[TextPart(content=body)])],
    )
    from app.chat.service import save_task_handoff

    save_task_handoff(session, task.chat_session_id, body)
    logger.warning(
        "runner: pausing task %d after %d consecutive reschedules",
        task_id,
        task.consecutive_reschedules,
    )
    update_task(session, task_id, TaskUpdate(assignee="user"))


def _handle_error_outcome(session: Session, task_id: int, error_text: str) -> None:
    """Surface a runner error in the task chat (and escalate at threshold).

    Caller has already committed the counter increment, so we re-read
    `consecutive_errors` for the branch decision. Below threshold: drop
    a one-line "I'll retry" message into the task chat. At threshold:
    drop a final "pausing this" message into the task chat and hand the
    task back to the user via `update_task`. Main-chat surfacing of the
    pause rides the task-terminal event drain (`app.chat.events`).
    """
    from app.tasks.schemas import TaskUpdate
    from app.tasks.service import update_task

    task = session.get(Task, task_id)
    if task is None:
        return

    chat_session_id = task.chat_session_id
    error_label = error_text or "unknown error"
    from app.knowledge.identity import resolve_assistant_name

    assistant_name = resolve_assistant_name()

    if task.consecutive_errors < ERROR_ESCALATION_THRESHOLD:
        body = ERROR_RETRY_TEMPLATE.format(assistant_name=assistant_name, error=error_label)
        save_new_messages(
            session,
            chat_session_id,
            [ModelResponse(parts=[TextPart(content=body)])],
        )
        return

    body = ERROR_PAUSE_TASK_CHAT_TEMPLATE.format(
        assistant_name=assistant_name, count=task.consecutive_errors, error=error_label
    )
    save_new_messages(
        session,
        chat_session_id,
        [ModelResponse(parts=[TextPart(content=body)])],
    )
    from app.chat.service import save_task_handoff

    save_task_handoff(session, chat_session_id, body)
    logger.warning(
        "runner: pausing task %d after %d consecutive errors",
        task_id,
        task.consecutive_errors,
    )
    update_task(session, task_id, TaskUpdate(assignee="user"))


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


def _successful_terminal_task_tool_return_seen(messages: list[ModelMessage]) -> bool:
    """Whether this turn has completed a terminal task tool successfully.

    Terminal task tools mutate durable task state and record the hidden
    handoff that wakes main chat. Once their tool return is persisted,
    the task wake is cleanly finished; requiring an additional final text
    response lets blank provider continuations become output-validation
    errors after the task already paused/completed/deferred.
    """
    for message in messages:
        for part in getattr(message, "parts", []) or []:
            if isinstance(part, ToolReturnPart) and part.tool_name in TERMINAL_TASK_TOOL_NAMES:
                content = part.content
                if isinstance(content, dict) and content.get("error"):
                    continue
                if isinstance(content, dict) and content.get("already_terminal"):
                    continue
                return True
    return False


def _stop_after_terminal_task_boundary(
    task_id: int | None,
    *,
    messages: list[ModelMessage],
) -> bool:
    if task_id is None:
        return False
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if task is None or not _task_in_terminal_state(task):
            return False
    if not _successful_terminal_task_tool_return_seen(messages):
        return False
    logger.info("runner: ending task %d turn after terminal tool return", task_id)
    return True


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

    if _main_loop is None or _main_loop.is_closed():
        logger.warning(
            "runner: no main loop captured, dropping wake for session %d "
            "— did app startup complete?",
            session_id,
        )
        return

    asyncio.run_coroutine_threadsafe(_wake_logged(session_id), _main_loop)
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


def _gap_for(task: Task) -> float:
    """Per-task minimum re-wake gap, in seconds.

    No errors → base 60s. Each consecutive error doubles the gap, capped
    at `WATCHDOG_MAX_GAP_SECONDS`. Stalls do not back off — the next tick
    after the base gap re-fires them with the reminder injected.
    """
    if task.consecutive_errors == 0:
        return WATCHDOG_BASE_GAP_SECONDS
    return min(
        WATCHDOG_BASE_GAP_SECONDS * (2 ** min(task.consecutive_errors, 4)),
        WATCHDOG_MAX_GAP_SECONDS,
    )


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
                if last is None or (now - last) >= WATCHDOG_BASE_GAP_SECONDS:
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
