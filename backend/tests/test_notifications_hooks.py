"""Hook-fires-once-per-event tests for the two event sources.

The hooks (`_fire_assistant_message_push`, `_fire_task_assigned_push`)
bridge sync-callsite → asyncio by scheduling the coroutine on the
running loop, so each test runs the trigger inside `asyncio.run(...)`
and awaits any pending tasks before asserting.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from app.chat import service as chat_service
from app.chat.models import ChatSession
from app.tasks.models import Task
from app.tasks.schemas import TaskUpdate
from app.tasks.service import update_task


class _CloseTrackingCoro:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_dedupe():
    from app.notifications.service import _dedupe

    _dedupe.clear()
    yield
    _dedupe.clear()


@pytest.fixture
def captured_notifies(monkeypatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake_notify(**kwargs: Any) -> None:
        calls.append(kwargs)

    from app.notifications import service as notif_service

    monkeypatch.setattr(notif_service, "notify", fake_notify)
    return calls


async def _drain_pending() -> None:
    """Wait for hook-spawned tasks to complete."""
    current = asyncio.current_task()
    pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


def test_notification_scheduler_closes_coroutine_when_no_loop(monkeypatch):
    from app.chat import runner
    from app.notifications import service as notif_service

    monkeypatch.setattr(runner, "_main_loop", None)
    coro = _CloseTrackingCoro()

    notif_service.schedule(coro, label="unit-test")  # type: ignore[arg-type]

    assert coro.closed is True


def test_assistant_response_in_main_session_fires_push(db_session, captured_notifies):
    main = chat_service.get_or_create_main_session(db_session)

    async def go() -> None:
        chat_service.save_new_messages(
            db_session,
            main.id,
            [ModelResponse(parts=[TextPart(content="hi from nix")])],
        )
        await _drain_pending()

    asyncio.run(go())

    assert any(
        c.get("event_type") == "assistant_message" and "hi from nix" in c.get("body", "")
        for c in captured_notifies
    )


def test_user_request_in_main_session_does_not_fire(db_session, captured_notifies):
    main = chat_service.get_or_create_main_session(db_session)

    async def go() -> None:
        chat_service.save_new_messages(
            db_session,
            main.id,
            [ModelRequest(parts=[UserPromptPart(content="hello")])],
        )
        await _drain_pending()

    asyncio.run(go())

    assert not any(c.get("event_type") == "assistant_message" for c in captured_notifies)


def test_assistant_response_in_task_chat_does_not_fire(db_session, captured_notifies):
    chat = ChatSession()
    db_session.add(chat)
    db_session.flush()
    task = Task(title="X", assignee="assistant", chat_session_id=chat.id)
    db_session.add(task)
    db_session.flush()
    chat.task_id = task.id
    db_session.commit()

    async def go() -> None:
        chat_service.save_new_messages(
            db_session,
            chat.id,
            [ModelResponse(parts=[TextPart(content="task chatter")])],
        )
        await _drain_pending()

    asyncio.run(go())

    assert not any(c.get("event_type") == "assistant_message" for c in captured_notifies)


def test_assignee_flip_to_user_fires_task_assigned(db_session, captured_notifies):
    chat = ChatSession()
    db_session.add(chat)
    db_session.flush()
    task = Task(title="Mow lawn", assignee="assistant", chat_session_id=chat.id)
    db_session.add(task)
    db_session.flush()
    chat.task_id = task.id
    db_session.commit()
    task_id = task.id

    async def go() -> None:
        update_task(db_session, task_id, TaskUpdate(assignee="user"))
        await _drain_pending()

    asyncio.run(go())

    assert any(
        c.get("event_type") == "task_assigned"
        and c.get("title") == "Mow lawn"
        and c.get("url") == f"/tasks/{task_id}"
        and c.get("body") == "Task is on you."
        for c in captured_notifies
    )


def test_assignee_flip_to_assistant_does_not_fire(db_session, captured_notifies):
    chat = ChatSession()
    db_session.add(chat)
    db_session.flush()
    task = Task(title="X", assignee="user", chat_session_id=chat.id)
    db_session.add(task)
    db_session.flush()
    chat.task_id = task.id
    db_session.commit()
    task_id = task.id

    async def go() -> None:
        update_task(db_session, task_id, TaskUpdate(assignee="assistant"))
        await _drain_pending()

    asyncio.run(go())

    assert not any(c.get("event_type") == "task_assigned" for c in captured_notifies)


def test_runner_error_streak_handoff_fires_task_assigned(db_session, captured_notifies):
    """`_persist_wake_outcome(errored=True)` hands the task back to the user
    once consecutive_errors hits the threshold. The handoff fires a single
    `task_assigned` push (the existing handoff plumbing) and no separate
    `task_errored` event — there is one push, not two, on the pause."""
    from app.chat import runner

    chat = ChatSession()
    db_session.add(chat)
    db_session.flush()
    task = Task(title="Flaky", assignee="assistant", chat_session_id=chat.id)
    db_session.add(task)
    db_session.flush()
    chat.task_id = task.id
    db_session.commit()
    task_id = task.id

    async def go() -> None:
        for _ in range(runner.ERROR_ESCALATION_THRESHOLD):
            runner._persist_wake_outcome(task_id, errored=True, error_text="boom")
        await _drain_pending()

    asyncio.run(go())

    assigned = [c for c in captured_notifies if c.get("event_type") == "task_assigned"]
    errored = [c for c in captured_notifies if c.get("event_type") == "task_errored"]
    assert len(assigned) == 1
    assert assigned[0].get("title") == "Flaky"
    assert assigned[0].get("url") == f"/tasks/{task_id}"
    assert errored == []
