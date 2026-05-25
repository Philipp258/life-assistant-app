"""Due-date scheduler tick semantics."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

import pytest

from app.chat.models import ChatSession
from app.tasks.models import Task
from app.tasks.schemas import TaskUpdate
from app.tasks.service import update_task


@pytest.fixture
def captured_notifies(monkeypatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake_notify(**kwargs: Any) -> None:
        calls.append(kwargs)

    from app.notifications import service

    monkeypatch.setattr(service, "notify", fake_notify)
    return calls


def _seed_task(
    db_session,
    *,
    due_at: datetime | None,
    is_done: bool = False,
) -> int:
    chat = ChatSession(kind="task")
    db_session.add(chat)
    db_session.flush()
    task = Task(
        title="Pay rent",
        assignee="user",
        due_at=due_at,
        is_done=is_done,
        chat_session_id=chat.id,
    )
    db_session.add(task)
    db_session.flush()
    chat.task_id = task.id
    db_session.commit()
    return task.id


def test_tick_fires_for_overdue_task_and_stamps_due_notified_at(db_session, captured_notifies):
    from app.notifications import due_scheduler

    task_id = _seed_task(db_session, due_at=datetime.utcnow() - timedelta(seconds=1))

    fired = asyncio.run(due_scheduler._tick(db_session))
    assert fired == 1
    assert any(c.get("event_type") == "task_due" for c in captured_notifies)

    db_session.expire_all()
    row = db_session.get(Task, task_id)
    assert row.due_notified_at is not None


def test_tick_does_not_refire_for_already_notified_task(db_session, captured_notifies):
    from app.notifications import due_scheduler

    _seed_task(db_session, due_at=datetime.utcnow() - timedelta(seconds=1))

    asyncio.run(due_scheduler._tick(db_session))
    captured_notifies.clear()
    fired = asyncio.run(due_scheduler._tick(db_session))
    assert fired == 0
    assert captured_notifies == []


def test_tick_skips_done_tasks(db_session, captured_notifies):
    from app.notifications import due_scheduler

    _seed_task(
        db_session,
        due_at=datetime.utcnow() - timedelta(seconds=1),
        is_done=True,
    )

    fired = asyncio.run(due_scheduler._tick(db_session))
    assert fired == 0
    assert captured_notifies == []


def test_update_task_clearing_due_at_resets_dedupe(db_session, captured_notifies):
    from app.notifications import due_scheduler

    task_id = _seed_task(db_session, due_at=datetime.utcnow() - timedelta(seconds=1))

    asyncio.run(due_scheduler._tick(db_session))
    captured_notifies.clear()

    new_due = datetime.utcnow() - timedelta(seconds=1)
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        update_task(db_session, task_id, TaskUpdate(due_at=new_due))
        pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
        if pending:
            loop.run_until_complete(asyncio.gather(*pending))
    finally:
        asyncio.set_event_loop(None)
        loop.close()

    db_session.expire_all()
    row = db_session.get(Task, task_id)
    assert row.due_notified_at is None

    fired = asyncio.run(due_scheduler._tick(db_session))
    assert fired == 1
    assert any(c.get("event_type") == "task_due" for c in captured_notifies)


def test_tick_skips_tasks_with_future_due_at(db_session, captured_notifies):
    from app.notifications import due_scheduler

    _seed_task(db_session, due_at=datetime.utcnow() + timedelta(hours=1))

    fired = asyncio.run(due_scheduler._tick(db_session))
    assert fired == 0
    assert captured_notifies == []
