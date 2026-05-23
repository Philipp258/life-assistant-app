"""Runner semantics — bypasses the real model with `agent.override`.

A wake is a single `agent.run` against the session. The agent's own
tool-call loop runs as many tools as it wants within that one call; the
runner just gates eligibility and persists the new messages.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from pydantic_ai import models
from pydantic_ai.models.function import AgentInfo
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from app.agent import get_agent
from app.agent.tools import tasks as task_tools
from app.chat import runner
from app.chat.models import ChatSession, Message
from app.chat.service import extract_task_handoff_text
from app.tasks.models import Task
from tests._function_model import build_function_model

models.ALLOW_MODEL_REQUESTS = False


@pytest.fixture
def _silence_main_wake(monkeypatch):
    """Stub the terminal→main wake seam.

    A real terminal wake schedules a main turn, which would build a real
    chat agent (no provider in unit tests). Tests that care about the
    hop patch `runner.wake_main_for_terminal` themselves.
    """

    def _noop(_task_session_id: int) -> None:
        return None

    monkeypatch.setattr(runner, "wake_main_for_terminal", _noop)
    return _noop


def _make_task_with_chat(Session, *, assignee: str = "assistant") -> tuple[int, int]:
    with Session() as s:
        chat = ChatSession()
        s.add(chat)
        s.flush()
        task = Task(
            title="Drive me",
            assignee=assignee,
            chat_session_id=chat.id,
        )
        s.add(task)
        s.flush()
        chat.task_id = task.id
        s.commit()
        return task.id, chat.id


def test_runner_pause_messages_allow_main_chat_reengagement():
    assert "Reply in main chat" in runner.ESCALATION_MESSAGE
    assert "relay the instruction back into this task" in runner.ESCALATION_MESSAGE
    assert "Reply in main chat" in runner.ERROR_PAUSE_TASK_CHAT_TEMPLATE


def _seed_user_message(Session, session_id: int) -> None:
    from app.chat.service import save_new_messages

    with Session() as s:
        save_new_messages(
            s,
            session_id,
            [ModelRequest(parts=[UserPromptPart(content="go")])],
        )


def _set_counters(
    Session,
    task_id: int,
    *,
    stalls: int = 0,
    errors: int = 0,
    reschedules: int = 0,
) -> None:
    with Session() as s:
        t = s.get(Task, task_id)
        assert t is not None
        t.consecutive_stalls = stalls
        t.consecutive_errors = errors
        t.consecutive_reschedules = reschedules
        s.commit()


def _get_counters(Session, task_id: int) -> tuple[int, int, int]:
    with Session() as s:
        t = s.get(Task, task_id)
        assert t is not None
        return t.consecutive_stalls, t.consecutive_errors, t.consecutive_reschedules


def _task_handoffs(Session, session_id: int) -> list[str]:
    handoffs: list[str] = []
    with Session() as s:
        rows = s.query(Message).filter(Message.session_id == session_id).order_by(Message.id).all()
    for row in rows:
        raw = row.parts_json if isinstance(row.parts_json, dict) else {}
        for part in raw.get("parts", []) or []:
            if not isinstance(part, dict):
                continue
            content = part.get("content")
            if not isinstance(content, str):
                continue
            handoff = extract_task_handoff_text(content)
            if handoff is not None:
                handoffs.append(handoff)
    return handoffs


def test_duplicate_complete_task_records_only_one_handoff(_test_db):
    Session = _test_db
    task_id, chat_id = _make_task_with_chat(Session)

    first = task_tools.do_complete_task(task_id, handoff="first final answer")
    second = task_tools.do_complete_task(task_id, handoff="second final answer")

    assert first["is_done"] is True
    assert second["already_terminal"] is True
    assert _task_handoffs(Session, chat_id) == ["first final answer"]


@pytest.mark.parametrize(
    ("first_call", "second_call"),
    [
        (
            lambda task_id: task_tools.do_reassign_task(
                task_id, assignee="user", handoff="need user input"
            ),
            lambda task_id: task_tools.do_complete_task(task_id, handoff="late completion"),
        ),
        (
            lambda task_id: task_tools.do_reschedule_task(
                task_id, datetime.now(UTC) + timedelta(hours=1), handoff="waiting until later"
            ),
            lambda task_id: task_tools.do_complete_task(task_id, handoff="late completion"),
        ),
    ],
)
def test_terminal_task_tools_do_not_record_handoffs_after_terminal_state(
    _test_db, first_call, second_call
):
    Session = _test_db
    task_id, chat_id = _make_task_with_chat(Session)

    first = first_call(task_id)
    second = second_call(task_id)

    assert first.get("error") is None
    assert second["already_terminal"] is True
    assert len(_task_handoffs(Session, chat_id)) == 1


def test_wake_runs_when_assigned_to_assistant(_test_db):
    """Plain text reply with no tool call leaves the task in-flight → stalled."""
    Session = _test_db
    _, chat_id = _make_task_with_chat(Session)
    _seed_user_message(Session, chat_id)

    runs = 0

    def handler(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        nonlocal runs
        runs += 1
        return ModelResponse(parts=[TextPart(content="working on it")])

    agent = get_agent()
    with agent.override(model=build_function_model(handler)):
        result = asyncio.run(runner.wake_session(chat_id))

    assert runs == 1
    assert result.outcome == "stalled"
    assert result.new_message_count >= 1

    with Session() as s:
        rows = s.query(Message).filter(Message.session_id == chat_id).all()
    # User message + agent response.
    assert len(rows) >= 2


def test_empty_task_bootstrap_prompt_is_saved_before_model_run(_test_db):
    """Fresh assistant tasks become visible in the task chat before the first turn finishes."""
    Session = _test_db
    _, chat_id = _make_task_with_chat(Session)

    observed_counts: list[int] = []

    def handler(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        with Session() as s:
            rows = s.query(Message).filter(Message.session_id == chat_id).all()
        observed_counts.append(len(rows))
        assert len(rows) == 1
        assert rows[0].kind == "request"
        return ModelResponse(parts=[TextPart(content="working on it")])

    agent = get_agent()
    with agent.override(model=build_function_model(handler)):
        result = asyncio.run(runner.wake_session(chat_id))

    assert observed_counts == [1]
    assert result.outcome == "stalled"
    assert result.new_message_count == 1
    with Session() as s:
        rows = s.query(Message).filter(Message.session_id == chat_id).order_by(Message.id).all()
    assert [row.kind for row in rows] == ["request", "response"]


def test_wake_publishes_runner_activity_events(_test_db):
    Session = _test_db
    _, chat_id = _make_task_with_chat(Session)
    _seed_user_message(Session, chat_id)

    def handler(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content="working on it")])

    async def run_and_collect() -> list[str]:
        from app.chat import pubsub

        async with pubsub.subscribe(chat_id) as queue:
            agent = get_agent()
            with agent.override(model=build_function_model(handler)):
                await runner.wake_session(chat_id)
            events = []
            while not queue.empty():
                events.append((await queue.get())["type"])
            return events

    events = asyncio.run(run_and_collect())

    assert events[0] == "runner_started"
    # Visible writes stream as keyed row upserts; the row id stays the
    # same when the final ModelResponse replaces the live partial.
    assert "message_upsert" in events
    assert events[-1] == "runner_finished"


def test_user_assigned_task_with_pending_message_runs_one_turn(_test_db):
    """Turn-based mode: a blocked (assignee='user') task with an
    unanswered user message runs exactly ONE agent turn — the user
    replied and expects a response. (Pre-fix this returned 'paused' and
    the agent never ran — the B1 regression.)"""
    Session = _test_db
    _, chat_id = _make_task_with_chat(Session, assignee="user")
    _seed_user_message(Session, chat_id)

    calls = 0

    def handler(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        return ModelResponse(parts=[TextPart(content="here you go")])

    agent = get_agent()
    with agent.override(model=build_function_model(handler)):
        result = asyncio.run(runner.wake_session(chat_id))

    assert calls == 1, "turn-based user-assigned task must run exactly one turn"
    # assignee stays 'user' → the wake is classified terminal.
    assert result.outcome == "terminated"


def test_wake_skips_user_assigned_task_with_no_pending_message(_test_db):
    """No unanswered user message on a user-assigned task → nothing to
    do; the agent must not run (no autonomous loop for assignee='user')."""
    Session = _test_db
    _, chat_id = _make_task_with_chat(Session, assignee="user")

    def handler(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        raise AssertionError("agent should not run with no pending user message")

    agent = get_agent()
    with agent.override(model=build_function_model(handler)):
        result = asyncio.run(runner.wake_session(chat_id))

    assert result.outcome == "paused"


def test_wake_skips_future_do_at(_test_db):
    Session = _test_db
    task_id, chat_id = _make_task_with_chat(Session)
    _seed_user_message(Session, chat_id)
    with Session() as s:
        task = s.get(Task, task_id)
        assert task is not None
        task.do_at = datetime.now(UTC) + timedelta(hours=1)
        s.commit()

    def handler(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        raise AssertionError("agent should not run before do_at")

    agent = get_agent()
    with agent.override(model=build_function_model(handler)):
        result = asyncio.run(runner.wake_session(chat_id))

    assert result.outcome == "scheduled"


def test_wake_skips_when_already_done(_test_db):
    Session = _test_db
    task_id, chat_id = _make_task_with_chat(Session)
    with Session() as s:
        t = s.get(Task, task_id)
        assert t is not None
        t.is_done = True
        s.commit()

    def handler(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        raise AssertionError("agent should not run when task is done")

    agent = get_agent()
    with agent.override(model=build_function_model(handler)):
        result = asyncio.run(runner.wake_session(chat_id))

    assert result.outcome == "already_done"


def test_wake_handles_unknown_session(_test_db):
    result = asyncio.run(runner.wake_session(99999))
    assert result.outcome == "no_task"


def test_wake_terminated_via_complete_resets_counters(_test_db, _silence_main_wake):
    """`complete_task` flips is_done; outcome is `terminated` and both counters reset."""
    Session = _test_db
    task_id, chat_id = _make_task_with_chat(Session)
    _seed_user_message(Session, chat_id)
    _set_counters(Session, task_id, stalls=2, errors=1, reschedules=4)

    call_count = 0

    def handler(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="complete_task",
                        args={"handoff": "completed cleanly"},
                        tool_call_id="c1",
                    ),
                ]
            )
        return ModelResponse(parts=[TextPart(content="all done")])

    agent = get_agent()
    with agent.override(model=build_function_model(handler)):
        result = asyncio.run(runner.wake_session(chat_id))

    assert result.outcome == "terminated"
    stalls, errors, reschedules = _get_counters(Session, task_id)
    assert stalls == 0
    assert errors == 0
    assert reschedules == 0
    with Session() as s:
        t = s.get(Task, task_id)
        assert t is not None
        assert t.is_done is True


def test_wake_terminated_via_reassign_resets_counters(_test_db, _silence_main_wake):
    Session = _test_db
    task_id, chat_id = _make_task_with_chat(Session)
    _seed_user_message(Session, chat_id)
    _set_counters(Session, task_id, stalls=2, errors=1, reschedules=4)

    call_count = 0

    def handler(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="reassign_task",
                        args={"assignee": "user", "handoff": "needs user input"},
                        tool_call_id="r1",
                    ),
                ]
            )
        return ModelResponse(parts=[TextPart(content="handed back")])

    agent = get_agent()
    with agent.override(model=build_function_model(handler)):
        result = asyncio.run(runner.wake_session(chat_id))

    assert result.outcome == "terminated"
    stalls, errors, reschedules = _get_counters(Session, task_id)
    assert stalls == 0
    assert errors == 0
    assert reschedules == 0


def test_ask_user_choice_ends_wake_before_empty_output_validation_retry(
    _test_db, _silence_main_wake
):
    """`ask_user_choice` pauses the task; a blank post-tool continuation
    must not turn that successful pause into an output-validation error.
    """
    Session = _test_db
    task_id, chat_id = _make_task_with_chat(Session)
    _seed_user_message(Session, chat_id)

    calls = 0
    question = (
        "Approve the proposed assistant-app-coding-agent skill update for "
        "future implementation tasks, or skip it for now?"
    )

    def handler(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="ask_user_choice",
                        args={
                            "question": question,
                            "options": ["Approve", "Revise", "Skip"],
                        },
                        tool_call_id="choice-1",
                    ),
                ]
            )
        return ModelResponse(parts=[])

    agent = get_agent()
    with agent.override(model=build_function_model(handler)):
        result = asyncio.run(runner.wake_session(chat_id))

    assert result.outcome == "terminated"
    assert calls == 1
    with Session() as s:
        task = s.get(Task, task_id)
        assert task is not None
        assert task.assignee == "user"

    parts = _parts_in_session(Session, chat_id)
    assert any(
        p.get("part_kind") == "tool-call" and p.get("tool_name") == "ask_user_choice" for p in parts
    )
    assert any(
        p.get("part_kind") == "tool-return" and p.get("tool_call_id") == "choice-1" for p in parts
    )
    assert not any(
        "Atlas hit an error" in text for text in _task_chat_text_messages(Session, chat_id)
    )


def test_terminal_tool_error_does_not_stop_user_assigned_task_turn(_test_db, _silence_main_wake):
    """A failed terminal-tool return is model feedback, not a clean
    terminal boundary, even when the task was already assigned to the user.
    """
    Session = _test_db
    task_id, chat_id = _make_task_with_chat(Session, assignee="user")
    _seed_user_message(Session, chat_id)

    calls = 0

    def handler(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="ask_user_choice",
                        args={"question": "Pick one", "options": ["Only one"]},
                        tool_call_id="bad-choice",
                    ),
                ]
            )
        return ModelResponse(parts=[TextPart(content="I need at least two choices.")])

    agent = get_agent()
    with agent.override(model=build_function_model(handler)):
        result = asyncio.run(runner.wake_session(chat_id))

    assert result.outcome == "terminated"
    assert calls == 2
    with Session() as s:
        task = s.get(Task, task_id)
        assert task is not None
        assert task.assignee == "user"

    parts = _parts_in_session(Session, chat_id)
    assert any(
        p.get("part_kind") == "tool-return"
        and p.get("tool_call_id") == "bad-choice"
        and isinstance(p.get("content"), dict)
        and p["content"].get("error")
        for p in parts
    )
    assert "I need at least two choices." in _task_chat_text_messages(Session, chat_id)


def test_wake_terminated_via_reschedule_tracks_reschedule_counter(_test_db, _silence_main_wake):
    """`reschedule_task` sets do_at to the future; runner sees terminal state."""
    Session = _test_db
    task_id, chat_id = _make_task_with_chat(Session)
    _seed_user_message(Session, chat_id)
    _set_counters(Session, task_id, stalls=2, errors=1, reschedules=4)

    future_at = (datetime.utcnow() + timedelta(hours=1)).isoformat()
    call_count = 0

    def handler(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="reschedule_task",
                        args={"do_at": future_at, "handoff": "check later"},
                        tool_call_id="s1",
                    ),
                ]
            )
        return ModelResponse(parts=[TextPart(content="parked")])

    agent = get_agent()
    with agent.override(model=build_function_model(handler)):
        result = asyncio.run(runner.wake_session(chat_id))

    assert result.outcome == "terminated"
    stalls, errors, reschedules = _get_counters(Session, task_id)
    assert stalls == 0
    assert errors == 0
    assert reschedules == 5
    with Session() as s:
        t = s.get(Task, task_id)
        assert t is not None
        assert t.do_at is not None and t.do_at > datetime.utcnow()
    # Future do_at hides the task from the watchdog.
    flight_session_ids = [t.chat_session_id for t in runner.list_in_flight_tasks()]
    assert chat_id not in flight_session_ids


def test_due_task_can_reschedule_again_after_previous_reschedule_handoff(
    _test_db, _silence_main_wake
):
    Session = _test_db
    task_id, chat_id = _make_task_with_chat(Session)
    _seed_user_message(Session, chat_id)

    future_times = [
        (datetime.utcnow() + timedelta(hours=1)).isoformat(),
        (datetime.utcnow() + timedelta(hours=2)).isoformat(),
    ]
    call_count = 0

    def handler(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        nonlocal call_count
        call_count += 1
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="reschedule_task",
                    args={"do_at": future_times.pop(0), "handoff": "check again"},
                    tool_call_id=f"s{len(future_times)}",
                ),
            ]
        )

    agent = get_agent()
    with agent.override(model=build_function_model(handler)):
        first = asyncio.run(runner.wake_session(chat_id))
        assert first.outcome == "terminated"

        with Session() as s:
            t = s.get(Task, task_id)
            assert t is not None
            t.do_at = datetime.utcnow() - timedelta(seconds=1)
            s.commit()

        second = asyncio.run(runner.wake_session(chat_id))

    assert second.outcome == "terminated"
    assert call_count == 2
    stalls, errors, reschedules = _get_counters(Session, task_id)
    assert stalls == 0
    assert errors == 0
    assert reschedules == 2


def test_reschedule_limit_pauses_task_after_fifty_deferrals(_test_db, _silence_main_wake):
    Session = _test_db
    task_id, chat_id = _make_task_with_chat(Session)
    _seed_user_message(Session, chat_id)
    _set_counters(
        Session,
        task_id,
        reschedules=runner.RESCHEDULE_ESCALATION_THRESHOLD - 1,
    )

    future_at = (datetime.utcnow() + timedelta(hours=1)).isoformat()
    call_count = 0

    def handler(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="reschedule_task",
                        args={"do_at": future_at, "handoff": "still waiting"},
                        tool_call_id="s1",
                    ),
                ]
            )
        return ModelResponse(parts=[TextPart(content="parked")])

    agent = get_agent()
    with agent.override(model=build_function_model(handler)):
        result = asyncio.run(runner.wake_session(chat_id))

    assert result.outcome == "terminated"
    with Session() as s:
        t = s.get(Task, task_id)
        assert t is not None
        assert t.assignee == "user"
        assert t.consecutive_reschedules == runner.RESCHEDULE_ESCALATION_THRESHOLD

    task_texts = _task_chat_text_messages(Session, chat_id)
    assert any("rescheduled this task 50 times in a row" in t for t in task_texts)
    assert any("deferring forever" in h for h in _task_handoffs(Session, chat_id))


def test_wake_stall_increments_counter(_test_db):
    Session = _test_db
    task_id, chat_id = _make_task_with_chat(Session)
    _seed_user_message(Session, chat_id)

    def handler(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content="thinking")])

    agent = get_agent()
    with agent.override(model=build_function_model(handler)):
        result = asyncio.run(runner.wake_session(chat_id))

    assert result.outcome == "stalled"
    stalls, errors, _reschedules = _get_counters(Session, task_id)
    assert stalls == 1
    assert errors == 0


def test_stall_reminder_appears_on_next_wake(_test_db):
    Session = _test_db
    task_id, chat_id = _make_task_with_chat(Session)
    _seed_user_message(Session, chat_id)
    _set_counters(Session, task_id, stalls=1)

    captured: list[list[ModelMessage]] = []

    def handler(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        captured.append(list(messages))
        return ModelResponse(parts=[TextPart(content="still thinking")])

    agent = get_agent()
    with agent.override(model=build_function_model(handler)):
        asyncio.run(runner.wake_session(chat_id))

    assert captured, "agent never called"
    history = captured[0]
    # Reminder is appended after own_history → it's a ModelRequest carrying
    # a SystemPromptPart with the locked reminder text.
    found = False
    for msg in history:
        for part in getattr(msg, "parts", []) or []:
            if (
                isinstance(part, SystemPromptPart)
                and "previous turn finished without ending the task" in part.content
            ):
                found = True
    assert found, "stall reminder not present in next wake's history"


def test_wake_error_increments_consecutive_errors(_test_db):
    Session = _test_db
    task_id, chat_id = _make_task_with_chat(Session)
    _seed_user_message(Session, chat_id)
    _set_counters(Session, task_id, stalls=2)

    async def boom(_session_id: int, _run_id: str = "") -> int:
        raise RuntimeError("provider down")

    with patch.object(runner, "run_session_turn", boom):
        result = asyncio.run(runner.wake_session(chat_id))

    assert result.outcome == "errored"
    stalls, errors, _reschedules = _get_counters(Session, task_id)
    # Errors do NOT touch the stall streak (strict).
    assert stalls == 2
    assert errors == 1


def test_consecutive_errors_does_not_reset_on_stall(_test_db):
    Session = _test_db
    task_id, chat_id = _make_task_with_chat(Session)
    _seed_user_message(Session, chat_id)
    _set_counters(Session, task_id, errors=2)

    def handler(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content="thinking")])

    agent = get_agent()
    with agent.override(model=build_function_model(handler)):
        asyncio.run(runner.wake_session(chat_id))

    stalls, errors, _reschedules = _get_counters(Session, task_id)
    assert stalls == 1
    # Strict: only `terminated` resets the error streak.
    assert errors == 2


def test_gap_for_returns_backoff_for_errors():
    base = runner.WATCHDOG_BASE_GAP_SECONDS
    cap = runner.WATCHDOG_MAX_GAP_SECONDS
    cases = [
        (0, base),
        (1, base * 2),
        (2, base * 4),
        (3, base * 8),
        (4, base * 16),
        (10, cap),
    ]
    for errors, expected in cases:
        t = Task(title="x", consecutive_errors=errors)
        assert runner._gap_for(t) == expected, (
            f"errors={errors}: got {runner._gap_for(t)}, want {expected}"
        )


def test_three_stalls_escalates_via_update_task(_test_db, _silence_main_wake):
    """After STALL_ESCALATION_THRESHOLD stalls the runner flips to user."""
    Session = _test_db
    task_id, chat_id = _make_task_with_chat(Session)
    _seed_user_message(Session, chat_id)

    def handler(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content="thinking")])

    agent = get_agent()
    with agent.override(model=build_function_model(handler)):
        for _ in range(runner.STALL_ESCALATION_THRESHOLD):
            asyncio.run(runner.wake_session(chat_id))

    with Session() as s:
        t = s.get(Task, task_id)
        assert t is not None
        assert t.assignee == "user"
        assert t.consecutive_stalls >= runner.STALL_ESCALATION_THRESHOLD

    # Watchdog skips user-assigned tasks.
    flight_session_ids = [t.chat_session_id for t in runner.list_in_flight_tasks()]
    assert chat_id not in flight_session_ids

    # Escalation message lands in the TASK chat (not auto-posted to main).
    # Surfacing to main chat is the main-chat handoff's call now.
    task_texts = _task_chat_text_messages(Session, chat_id)
    assert any("three times in a row" in t for t in task_texts)

    from app.chat.service import get_or_create_main_session

    with Session() as s:
        main = get_or_create_main_session(s)
        main_msgs = s.query(Message).filter(Message.session_id == main.id).all()
    # Notification pass is stubbed; nothing else should have posted to main.
    assert main_msgs == []


def test_assignee_flip_to_assistant_resets_counters(_test_db):
    """User re-engagement (assignee→assistant) zeros runner counters."""
    from app.tasks.schemas import TaskUpdate
    from app.tasks.service import update_task

    Session = _test_db
    task_id, chat_id = _make_task_with_chat(Session, assignee="user")
    _set_counters(Session, task_id, stalls=2, errors=1, reschedules=4)

    with Session() as s:
        update_task(s, task_id, TaskUpdate(assignee="assistant"))

    stalls, errors, reschedules = _get_counters(Session, task_id)
    assert stalls == 0
    assert errors == 0
    assert reschedules == 0
    # Sanity: chat still bound.
    with Session() as s:
        t = s.get(Task, task_id)
        assert t is not None
        assert t.assignee == "assistant"
        assert t.chat_session_id == chat_id


def test_recurring_spawn_starts_with_zero_counters(_test_db):
    """A recurring task's next cycle row starts with fresh counters."""
    from app.tasks.schemas import TaskUpdate
    from app.tasks.service import update_task

    Session = _test_db
    with Session() as s:
        chat = ChatSession()
        s.add(chat)
        s.flush()
        task = Task(
            title="Weekly thing",
            assignee="assistant",
            chat_session_id=chat.id,
            interval_unit="week",
            interval_count=1,
            do_at=datetime.utcnow() - timedelta(days=7),
            consecutive_stalls=2,
            consecutive_errors=1,
        )
        s.add(task)
        s.flush()
        chat.task_id = task.id
        s.commit()
        task_id = task.id

    with Session() as s:
        update_task(s, task_id, TaskUpdate(is_done=True))

    with Session() as s:
        rows = s.query(Task).all()
    # Two rows: the completed one and the spawned next instance.
    assert len(rows) == 2
    spawned = [r for r in rows if r.id != task_id][0]
    assert spawned.consecutive_stalls == 0
    assert spawned.consecutive_errors == 0
    # The spawned cycle gets its own non-NULL chat session (NOT NULL
    # invariant) distinct from the predecessor's chat.
    assert spawned.chat_session_id is not None
    with Session() as s:
        chat = s.get(ChatSession, spawned.chat_session_id)
        assert chat is not None
        assert chat.task_id == spawned.id


def _task_chat_text_messages(Session, chat_id: int) -> list[str]:
    """Pull text content out of every persisted message in `chat_id`."""
    out: list[str] = []
    with Session() as s:
        rows = s.query(Message).filter(Message.session_id == chat_id).order_by(Message.id).all()
        for row in rows:
            for part in (row.parts_json or {}).get("parts", []) or []:
                if isinstance(part, dict) and (
                    part.get("part_kind") == "text" or part.get("kind") == "text"
                ):
                    content = part.get("content")
                    if isinstance(content, str):
                        out.append(content)
    return out


def test_wake_error_appends_retry_notice_to_task_chat(_test_db):
    """First/second hard error: the task chat gets a sanitized retry notice."""
    Session = _test_db
    _, chat_id = _make_task_with_chat(Session)
    _seed_user_message(Session, chat_id)

    async def boom(_session_id: int, _run_id: str = "") -> int:
        raise RuntimeError("provider down")

    with patch.object(runner, "run_session_turn", boom):
        result = asyncio.run(runner.wake_session(chat_id))

    assert result.outcome == "errored"
    texts = _task_chat_text_messages(Session, chat_id)
    assert any(
        "Atlas hit an error" in t and "retry" in t and "RuntimeError: provider down" in t
        for t in texts
    ), texts


def test_wake_error_threshold_pauses_task_no_main_post(_test_db, _silence_main_wake):
    """Third hard error: final pause notice in task chat + handoff to user.
    Main-chat surfacing is delegated to the main-chat handoff (stubbed here).
    """
    Session = _test_db
    task_id, chat_id = _make_task_with_chat(Session)
    _seed_user_message(Session, chat_id)
    _set_counters(Session, task_id, errors=runner.ERROR_ESCALATION_THRESHOLD - 1)

    async def boom(_session_id: int, _run_id: str = "") -> int:
        raise RuntimeError("provider down")

    with patch.object(runner, "run_session_turn", boom):
        result = asyncio.run(runner.wake_session(chat_id))

    assert result.outcome == "errored"

    with Session() as s:
        t = s.get(Task, task_id)
        assert t is not None
        assert t.assignee == "user"
        assert t.consecutive_errors >= runner.ERROR_ESCALATION_THRESHOLD

    # Watchdog skips user-assigned tasks.
    flight_session_ids = [t.chat_session_id for t in runner.list_in_flight_tasks()]
    assert chat_id not in flight_session_ids

    # Final pause notice landed in the task chat.
    task_chat_texts = _task_chat_text_messages(Session, chat_id)
    assert any("pausing it instead of retrying forever" in t for t in task_chat_texts)

    # No automatic main-chat post — main-chat handoff would handle that.
    from app.chat.service import get_or_create_main_session

    with Session() as s:
        main = get_or_create_main_session(s)
        main_msgs = s.query(Message).filter(Message.session_id == main.id).all()
    assert main_msgs == []


def test_terminated_wake_wakes_main(_test_db, monkeypatch):
    """Every wake that lands in a terminal state wakes the main session."""
    Session = _test_db
    _, chat_id = _make_task_with_chat(Session)
    _seed_user_message(Session, chat_id)

    seen: list[int] = []
    monkeypatch.setattr(runner, "wake_main_for_terminal", lambda sid: seen.append(sid))

    call_count = 0

    def handler(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="complete_task",
                        args={"handoff": "done"},
                        tool_call_id="c1",
                    )
                ]
            )
        return ModelResponse(parts=[TextPart(content="done")])

    agent = get_agent()
    with agent.override(model=build_function_model(handler)):
        result = asyncio.run(runner.wake_session(chat_id))

    assert result.outcome == "terminated"
    assert seen == [chat_id]


def test_stalled_wake_skips_main(_test_db, monkeypatch):
    """Soft stalls (mid-streak, no escalation) do NOT wake main."""
    Session = _test_db
    _, chat_id = _make_task_with_chat(Session)
    _seed_user_message(Session, chat_id)

    seen: list[int] = []
    monkeypatch.setattr(runner, "wake_main_for_terminal", lambda sid: seen.append(sid))

    def handler(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content="thinking")])

    agent = get_agent()
    with agent.override(model=build_function_model(handler)):
        result = asyncio.run(runner.wake_session(chat_id))

    assert result.outcome == "stalled"
    assert seen == []


def test_stall_escalation_wakes_main(_test_db, monkeypatch):
    """When a stall flips the task to user, main is woken (terminal state)."""
    Session = _test_db
    task_id, chat_id = _make_task_with_chat(Session)
    _seed_user_message(Session, chat_id)
    _set_counters(Session, task_id, stalls=runner.STALL_ESCALATION_THRESHOLD - 1)

    seen: list[int] = []
    monkeypatch.setattr(runner, "wake_main_for_terminal", lambda sid: seen.append(sid))

    def handler(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content="still thinking")])

    agent = get_agent()
    with agent.override(model=build_function_model(handler)):
        asyncio.run(runner.wake_session(chat_id))

    assert seen == [chat_id]


def test_error_escalation_wakes_main(_test_db, monkeypatch):
    """At the error threshold the task flips to user — main is woken."""
    Session = _test_db
    task_id, chat_id = _make_task_with_chat(Session)
    _seed_user_message(Session, chat_id)
    _set_counters(Session, task_id, errors=runner.ERROR_ESCALATION_THRESHOLD - 1)

    seen: list[int] = []
    monkeypatch.setattr(runner, "wake_main_for_terminal", lambda sid: seen.append(sid))

    async def boom(_session_id: int, _run_id: str = "") -> int:
        raise RuntimeError("provider down")

    with patch.object(runner, "run_session_turn", boom):
        asyncio.run(runner.wake_session(chat_id))

    assert seen == [chat_id]


def test_mid_streak_error_skips_main(_test_db, monkeypatch):
    """An error wake below escalation threshold stays in flight — no main wake."""
    Session = _test_db
    _, chat_id = _make_task_with_chat(Session)
    _seed_user_message(Session, chat_id)

    seen: list[int] = []
    monkeypatch.setattr(runner, "wake_main_for_terminal", lambda sid: seen.append(sid))

    async def boom(_session_id: int, _run_id: str = "") -> int:
        raise RuntimeError("provider down")

    with patch.object(runner, "run_session_turn", boom):
        asyncio.run(runner.wake_session(chat_id))

    assert seen == []


def test_wake_main_for_terminal_schedules_main_session(_test_db, monkeypatch):
    """The real seam resolves the singleton main session and schedules a
    wake for *it* (not the task chat)."""
    from app.chat.service import get_or_create_main_session

    Session = _test_db
    _, chat_id = _make_task_with_chat(Session)
    with Session() as s:
        main_id = get_or_create_main_session(s).id

    scheduled: list[int] = []
    monkeypatch.setattr(runner, "schedule_wake", lambda sid: scheduled.append(sid))

    runner.wake_main_for_terminal(chat_id)
    assert scheduled == [main_id]

    # No self-wake if the "task" session somehow is the main session.
    scheduled.clear()
    runner.wake_main_for_terminal(main_id)
    assert scheduled == []


def test_main_wake_skips_when_nothing_to_drain(_test_db):
    """A main wake with no undrained task-terminal events is a cheap
    no-op — `wake_session` never builds the agent."""
    from app.chat.service import get_or_create_main_session

    Session = _test_db
    with Session() as s:
        main_id = get_or_create_main_session(s).id

    agent = get_agent()

    def handler(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        raise AssertionError("main turn should not run with nothing to drain")

    with agent.override(model=build_function_model(handler)):
        result = asyncio.run(runner.wake_session(main_id))
    assert result.outcome == "no_events"


def _seed_handoff_and_main(Session) -> tuple[int, int, int]:
    """One task handoff + the main session. Returns (chat, main, row_id)."""
    from app.chat import events
    from app.chat.service import get_or_create_main_session, save_task_handoff

    _, chat_id = _make_task_with_chat(Session)
    with Session() as s:
        save_task_handoff(s, chat_id, "Backup ok, nothing to report.")
        main_id = get_or_create_main_session(s).id
    with Session() as s:
        row_id = events.latest_terminal_event_id(s)
    assert row_id is not None
    return chat_id, main_id, row_id


def _main_cursor(Session, main_id: int) -> int | None:
    with Session() as s:
        return s.get(ChatSession, main_id).event_cursor_id


def test_main_drain_silence_advances_cursor_no_row_no_push(_test_db, monkeypatch):
    """Model calls the `do_nothing` output tool: the run ends silent.
    The event cursor still advances (exactly-once preserved) but no
    visible row is persisted and no push fires."""
    from app.chat import service

    Session = _test_db
    _, main_id, row_id = _seed_handoff_and_main(Session)

    pushes: list[int] = []
    monkeypatch.setattr(
        service,
        "_fire_assistant_message_push",
        lambda row, sid: pushes.append(sid),
    )

    def handler(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        # The terminating output tool — pydantic-ai ends the run here with
        # `result.output` a `StaySilent`, no assistant text possible.
        return ModelResponse(parts=[ToolCallPart(tool_name="do_nothing", args={})])

    agent = get_agent()
    with agent.override(model=build_function_model(handler)):
        result = asyncio.run(runner.wake_session(main_id))

    assert result.outcome == "completed"
    # Cursor advanced past the handoff → no re-drain, exactly-once holds.
    assert _main_cursor(Session, main_id) == row_id
    # Nothing visible persisted: no reply, no `do_nothing` tool junk.
    assert _parts_in_session(Session, main_id) == []
    assert pushes == []

    # A second wake has nothing to drain — proves the cursor stuck.
    with agent.override(model=build_function_model(handler)):
        again = asyncio.run(runner.wake_session(main_id))
    assert again.outcome == "no_events"


def test_main_drain_reply_persists_one_row_and_pushes_once(_test_db, monkeypatch):
    """Model replies with text: exactly one assistant row persists, push
    fires once, cursor advances once (no duplicate on the next wake)."""
    from app.chat import service

    Session = _test_db
    _, main_id, row_id = _seed_handoff_and_main(Session)

    pushes: list[int] = []
    monkeypatch.setattr(
        service,
        "_fire_assistant_message_push",
        lambda row, sid: pushes.append(sid),
    )

    def handler(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content="Backup finished, all good.")])

    agent = get_agent()
    with agent.override(model=build_function_model(handler)):
        result = asyncio.run(runner.wake_session(main_id))

    assert result.outcome == "completed"
    assert _main_cursor(Session, main_id) == row_id
    parts = _parts_in_session(Session, main_id)
    texts = [p.get("content") for p in parts if p.get("part_kind") == "text"]
    assert texts == ["Backup finished, all good."]
    assert pushes == [main_id]

    # Cursor advanced → the next wake finds nothing, no duplicate reply.
    with agent.override(model=build_function_model(handler)):
        again = asyncio.run(runner.wake_session(main_id))
    assert again.outcome == "no_events"
    assert pushes == [main_id]


def test_single_flight_user_turn_and_event_wake_serialize(_test_db):
    """The lock is shared between the router's user turn and an event
    wake. While one holds `_session_locks[sid]`, the other blocks — no
    two turns for the same session run concurrently."""
    Session = _test_db
    _, chat_id = _make_task_with_chat(Session)
    _seed_user_message(Session, chat_id)

    async def scenario() -> str:
        lock = runner._session_locks[chat_id]
        await lock.acquire()  # stand in for an in-flight router turn
        try:
            wake = asyncio.create_task(runner.wake_session(chat_id))
            await asyncio.sleep(0.05)
            # The wake cannot have run while we hold the lock.
            assert not wake.done(), "wake ran while the session lock was held"
        finally:
            lock.release()
        return (await wake).outcome

    def handler(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content="ran after lock freed")])

    agent = get_agent()
    with agent.override(model=build_function_model(handler)):
        outcome = asyncio.run(scenario())
    # Once the lock frees the wake proceeds and runs a real turn.
    assert outcome == "stalled"


def test_watchdog_rewakes_main_until_drained(_test_db, monkeypatch):
    """Kind-agnostic safety net: the watchdog re-pokes the main session
    whenever it still has undrained task-terminal events, and stops once
    the cursor has caught up."""
    from app.chat import events
    from app.chat.service import get_or_create_main_session, save_task_handoff

    Session = _test_db
    _, chat_id = _make_task_with_chat(Session)
    with Session() as s:
        save_task_handoff(s, chat_id, "blocked — need a decision")
        main_id = get_or_create_main_session(s).id

    async def run_watchdog_briefly() -> list[int]:
        woke: list[int] = []

        async def fake_logged(sid: int) -> None:
            woke.append(sid)

        monkeypatch.setattr(runner, "_wake_logged", fake_logged)

        real_sleep = asyncio.sleep

        async def fast_sleep(_seconds: float) -> None:
            await real_sleep(0)

        monkeypatch.setattr(runner.asyncio, "sleep", fast_sleep)

        wd = asyncio.create_task(runner._watchdog_loop())
        # Let several watchdog iterations + the scheduled fake wakes run.
        for _ in range(20):
            await real_sleep(0)
        wd.cancel()
        try:
            await wd
        except asyncio.CancelledError:
            pass
        for _ in range(5):
            await real_sleep(0)  # flush any still-pending fake wakes
        return woke

    woke = asyncio.run(run_watchdog_briefly())
    assert main_id in woke, woke

    # Drain + advance the cursor (a finished main turn). Now the watchdog
    # must leave main alone.
    with Session() as s:
        _injected, seen = events.drain_terminal_events(s, main_id)
        events.advance_event_cursor(s, main_id, seen=seen)

    woke_after = asyncio.run(run_watchdog_briefly())
    assert main_id not in woke_after, woke_after


def test_list_in_flight_tasks(_test_db):
    Session = _test_db
    _, chat_running = _make_task_with_chat(Session)
    _, chat_paused = _make_task_with_chat(Session, assignee="user")
    task_done_id, _ = _make_task_with_chat(Session)
    with Session() as s:
        t = s.get(Task, task_done_id)
        assert t is not None
        t.is_done = True
        s.commit()

    flight = runner.list_in_flight_tasks()
    session_ids = [t.chat_session_id for t in flight]
    assert chat_running in session_ids
    assert chat_paused not in session_ids


def test_persist_wake_outcome_accepts_offset_aware_do_at(monkeypatch, db_session):
    from datetime import UTC

    from app.chat.models import ChatSession
    from app.chat.runner import _persist_wake_outcome
    from app.tasks.models import Task

    chat = ChatSession()
    db_session.add(chat)
    db_session.flush()
    task = Task(
        title="Aware future",
        assignee="assistant",
        chat_session_id=chat.id,
        do_at=datetime(2099, 4, 27, 14, 30, tzinfo=UTC),
    )
    db_session.add(task)
    db_session.commit()
    chat.task_id = task.id
    db_session.commit()

    outcome = _persist_wake_outcome(task.id)

    assert outcome == "terminated"


def _parts_in_session(Session, chat_id: int) -> list[dict]:
    """Flatten every saved part across messages, in row order."""
    with Session() as s:
        rows = s.query(Message).filter(Message.session_id == chat_id).order_by(Message.id).all()
    flat: list[dict] = []
    for row in rows:
        for part in (row.parts_json or {}).get("parts", []) or []:
            if isinstance(part, dict):
                flat.append(part)
    return flat


def test_mid_loop_user_correction_restarts_before_tool_iteration(
    _test_db, _silence_main_wake, monkeypatch
):
    """A task-chat correction that lands after history load stops the
    current graph before the planned tool runs. The dangling tool call is
    closed so the fresh wake can reload valid provider history.
    """
    from app.chat.service import save_new_messages

    Session = _test_db
    task_id, chat_id = _make_task_with_chat(Session)
    _seed_user_message(Session, chat_id)
    _set_counters(Session, task_id, stalls=1, errors=1)

    scheduled: list[int] = []
    monkeypatch.setattr(runner, "schedule_wake", lambda sid: scheduled.append(sid))
    monkeypatch.setattr(
        task_tools,
        "do_list_tasks",
        lambda **_kwargs: pytest.fail("stale run should stop before list_tasks executes"),
    )

    calls = 0
    second_wake_saw_correction = False

    def handler(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        nonlocal calls, second_wake_saw_correction
        calls += 1
        correction_seen = any(
            isinstance(message, ModelRequest)
            and any(
                isinstance(part, UserPromptPart) and "please stop" in str(part.content)
                for part in message.parts
            )
            for message in messages
        )
        if correction_seen:
            second_wake_saw_correction = True
            return ModelResponse(parts=[TextPart(content="saw the correction")])

        with Session() as s:
            save_new_messages(
                s,
                chat_id,
                [ModelRequest(parts=[UserPromptPart(content="please stop")])],
            )
        return ModelResponse(
            parts=[ToolCallPart(tool_name="list_tasks", args={}, tool_call_id="stale-tool")]
        )

    agent = get_agent()
    with agent.override(model=build_function_model(handler)):
        first = asyncio.run(runner.wake_session(chat_id))
        assert _get_counters(Session, task_id) == (1, 1, 0)
        second = asyncio.run(runner.wake_session(chat_id))

    assert first.outcome == "restarted"
    assert first.new_message_count >= 2
    assert scheduled == [chat_id]
    assert calls == 2
    assert second.outcome == "stalled"
    assert second_wake_saw_correction is True
    assert _get_counters(Session, task_id) == (2, 1, 0)

    parts = _parts_in_session(Session, chat_id)
    assert any(
        p.get("part_kind") == "tool-call" and p.get("tool_call_id") == "stale-tool" for p in parts
    )
    assert any(
        p.get("part_kind") == "tool-return" and p.get("tool_call_id") == "stale-tool" for p in parts
    )


def test_mid_loop_relay_restarts_after_completed_tool_result(
    _test_db, _silence_main_wake, monkeypatch
):
    """A relayed correction during a tool call is picked up after the
    tool node flushes, before the stale loop can make another model call.
    """
    from app.chat.service import save_new_messages

    Session = _test_db
    _, chat_id = _make_task_with_chat(Session)
    _seed_user_message(Session, chat_id)
    with Session() as s:
        source = ChatSession(kind="main")
        s.add(source)
        s.commit()
        source_id = source.id

    scheduled: list[int] = []
    monkeypatch.setattr(runner, "schedule_wake", lambda sid: scheduled.append(sid))

    def relay_during_tool(**_kwargs):
        with Session() as s:
            save_new_messages(
                s,
                chat_id,
                [ModelResponse(parts=[TextPart(content="relay: use the new constraint")])],
                source_session_id=source_id,
            )
        return {"tasks": [], "total": 0, "offset": 0, "limit": 50, "has_more": False}

    monkeypatch.setattr(task_tools, "do_list_tasks", relay_during_tool)

    calls = 0
    second_wake_saw_relay = False

    def handler(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        nonlocal calls, second_wake_saw_relay
        calls += 1
        relay_seen = any(
            isinstance(message, ModelResponse)
            and any(
                isinstance(part, TextPart) and "new constraint" in part.content
                for part in message.parts
            )
            for message in messages
        )
        if relay_seen:
            second_wake_saw_relay = True
            return ModelResponse(parts=[TextPart(content="saw the relay")])
        return ModelResponse(
            parts=[ToolCallPart(tool_name="list_tasks", args={}, tool_call_id="relay-tool")]
        )

    agent = get_agent()
    with agent.override(model=build_function_model(handler)):
        first = asyncio.run(runner.wake_session(chat_id))
        second = asyncio.run(runner.wake_session(chat_id))

    assert first.outcome == "restarted"
    assert scheduled == [chat_id]
    assert calls == 2
    assert second.outcome == "stalled"
    assert second_wake_saw_relay is True

    parts = _parts_in_session(Session, chat_id)
    assert any(
        p.get("part_kind") == "tool-return" and p.get("tool_call_id") == "relay-tool" for p in parts
    )
    with Session() as s:
        relays = (
            s.query(Message)
            .filter(Message.session_id == chat_id, Message.source_session_id == source_id)
            .all()
        )
    assert len(relays) == 1


def test_run_session_turn_persists_partial_progress_on_error(_test_db):
    """If the LLM provider dies on the second turn after a successful tool
    call, the user-visible tool call + tool return must already be in the
    DB. Previously the runner buffered everything in `result.new_messages()`
    and lost it all on exception.
    """
    Session = _test_db
    _, chat_id = _make_task_with_chat(Session)
    _seed_user_message(Session, chat_id)

    call_count = 0

    def handler(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="list_tasks",
                        args={},
                        tool_call_id="t1",
                    ),
                ]
            )
        raise RuntimeError("provider down")

    agent = get_agent()
    with agent.override(model=build_function_model(handler)):
        with pytest.raises(Exception):
            asyncio.run(runner.run_session_turn(chat_id))

    parts = _parts_in_session(Session, chat_id)
    # The user prompt, the tool call, and the tool return should all be persisted
    # despite the second model call raising.
    kinds = [p.get("part_kind") for p in parts]
    assert "user-prompt" in kinds, kinds
    assert "tool-call" in kinds, kinds
    assert "tool-return" in kinds, kinds
    # Specifically the list_tasks call and its return survive the error.
    assert any(
        p.get("part_kind") == "tool-call" and p.get("tool_name") == "list_tasks" for p in parts
    )
    assert any(p.get("part_kind") == "tool-return" and p.get("tool_call_id") == "t1" for p in parts)


def test_wake_partial_progress_persisted_then_error_marker(_test_db):
    """End-to-end: a wake that errors after a successful tool call shows
    the partial assistant turn AND the runner's error notice in the task chat.
    """
    Session = _test_db
    _, chat_id = _make_task_with_chat(Session)
    _seed_user_message(Session, chat_id)

    call_count = 0

    def handler(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="list_tasks",
                        args={},
                        tool_call_id="t1",
                    ),
                ]
            )
        raise RuntimeError("provider down")

    agent = get_agent()
    with agent.override(model=build_function_model(handler)):
        result = asyncio.run(runner.wake_session(chat_id))

    assert result.outcome == "errored"

    parts = _parts_in_session(Session, chat_id)
    assert any(
        p.get("part_kind") == "tool-call" and p.get("tool_name") == "list_tasks" for p in parts
    )
    assert any(p.get("part_kind") == "tool-return" and p.get("tool_call_id") == "t1" for p in parts)

    # The runner's retry notice still lands after the partial turn.
    texts = _task_chat_text_messages(Session, chat_id)
    assert any("Atlas hit an error" in t and "RuntimeError: provider down" in t for t in texts)


def test_close_dangling_tool_calls_appends_synthetic_returns():
    """`close_dangling_tool_calls` keeps balanced histories untouched and
    appends interruption-marker returns for any open tool_call_ids."""
    from app.chat.repair import close_dangling_tool_calls

    balanced = [
        ModelRequest(parts=[UserPromptPart(content="hi")]),
        ModelResponse(parts=[ToolCallPart(tool_name="x", args={}, tool_call_id="a")]),
        ModelRequest(parts=[ToolReturnPart(tool_name="x", tool_call_id="a", content="ok")]),
    ]
    assert close_dangling_tool_calls(balanced) == balanced

    dangling = [
        ModelRequest(parts=[UserPromptPart(content="hi")]),
        ModelResponse(parts=[ToolCallPart(tool_name="y", args={}, tool_call_id="b")]),
    ]
    closed = close_dangling_tool_calls(dangling)
    assert len(closed) == 3
    last = closed[-1]
    assert isinstance(last, ModelRequest)
    returns = [p for p in last.parts if isinstance(p, ToolReturnPart)]
    assert len(returns) == 1
    assert returns[0].tool_call_id == "b"
    assert returns[0].tool_name == "y"
    assert "interrupted" in str(returns[0].content).lower()
