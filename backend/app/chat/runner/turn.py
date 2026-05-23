"""Single agent turn: `run_session_turn` plus its boundary helpers.

One `agent.iter()` per call, persisting incrementally (or atomically
with the event cursor on a main-chat drain turn). Per-kind behavior is
captured by `app.chat.session_policy.resolve_kind` and the surrounding
event drain / stall reminder logic.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic_ai import Agent
from pydantic_ai._agent_graph import ModelRequestNode
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
)
from pydantic_graph.nodes import End

from app.agent import build_system_prompt, get_agent
from app.agent.deps import AgentDeps
from app.agent.usage import default_usage_limits
from app.chat import events, pubsub
from app.chat.models import ChatSession, Message
from app.chat.repair import close_dangling_tool_calls, repair_persisted_history
from app.chat.service import (
    aload_compacted_history,
    create_streaming_response_row,
    load_session_history_with_cursor,
    publish_streaming_text_upsert,
    save_new_messages,
    update_streaming_response_row,
)
from app.chat.session_policy import resolve_kind
from app.db import SessionLocal
from app.tasks.models import Task

from .claims import _get_task_for_session, _task_in_terminal_state
from .inputs import _has_new_task_input_since
from .messages import (
    TERMINAL_TASK_TOOL_NAMES,
    _StaleTaskInputRestart,
    _build_bootstrap_request,
    _build_stall_reminder,
)
from .state import _pending_voice

logger = logging.getLogger(__name__)


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
        bootstrap = _build_bootstrap_request(task)
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
    # here) it would call the model with no system prompt — wrong
    # identity, no memory/tools guidance, no voice marker. Prepend a
    # freshly built prompt instead. Do NOT strip existing
    # SystemPromptParts: the stall reminder and task handoffs are
    # deliberately SystemPromptPart-only ModelRequests and must survive
    # (a capability with `replace_existing` would eat them and break the
    # "history ends with a ModelRequest" invariant).
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

    async def _stream_text(node: ModelRequestNode[AgentDeps, Any]) -> None:
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
        async with node.stream(agent_run.ctx) as request_stream:
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
        # with the handoff un-cursored (which would re-drain it on the
        # next wake and have the model answer it twice).
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
