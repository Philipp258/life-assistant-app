"""Phase 4 — recurrence-on-completion, do_at gating, save_core_memory tool."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.chat import runner
from app.chat.models import ChatSession
from app.tasks import service as tasks_service
from app.tasks.models import Task
from app.tasks.schemas import TaskCreate, TaskUpdate


def _make_recurring_task(Session, *, do_at: datetime | None = None) -> int:
    with Session() as s:
        task = tasks_service.create_task(
            s,
            TaskCreate(
                title="Daily check-in",
                description="Daily.",
                assignee="user",
                do_at=do_at,
                interval_unit="day",
                interval_count=1,
            ),
        )
        return task.id


def test_completing_recurring_task_spawns_next_instance(_test_db):
    Session = _test_db
    initial_due = datetime(2026, 4, 26, 9, 0)
    task_id = _make_recurring_task(Session, do_at=initial_due)

    with Session() as s:
        before = s.query(Task).count()
        prev_chat_id = s.get(Task, task_id).chat_session_id

    with Session() as s:
        tasks_service.update_task(s, task_id, TaskUpdate(is_done=True))

    with Session() as s:
        after = s.query(Task).order_by(Task.id).all()
    assert len(after) == before + 1
    spawned = after[-1]
    assert spawned.id != task_id
    assert spawned.is_done is False
    assert spawned.title == "Daily check-in"
    assert spawned.description == "Daily."
    assert spawned.interval_unit == "day"
    assert spawned.interval_count == 1
    assert spawned.do_at == initial_due + timedelta(days=1)
    assert spawned.chat_session_id is not None
    assert spawned.chat_session_id != prev_chat_id

    with Session() as s:
        new_chat = s.get(ChatSession, spawned.chat_session_id)
        assert new_chat is not None
        assert new_chat.task_id == spawned.id


def test_completing_non_recurring_task_does_not_spawn(_test_db):
    Session = _test_db
    with Session() as s:
        t = tasks_service.create_task(s, TaskCreate(title="One-off", assignee="user"))
        task_id = t.id

    with Session() as s:
        before = s.query(Task).count()

    with Session() as s:
        tasks_service.update_task(s, task_id, TaskUpdate(is_done=True))

    with Session() as s:
        after = s.query(Task).count()
    assert after == before


def test_recurrence_anchors_on_now_when_no_prev_do_at(_test_db):
    Session = _test_db
    with Session() as s:
        t = tasks_service.create_task(
            s,
            TaskCreate(
                title="Loose recurring",
                assignee="user",
                interval_unit="hour",
                interval_count=2,
            ),
        )
        task_id = t.id

    before = datetime.utcnow()
    with Session() as s:
        tasks_service.update_task(s, task_id, TaskUpdate(is_done=True))
    after = datetime.utcnow()

    with Session() as s:
        spawned = s.query(Task).order_by(Task.id.desc()).first()
    assert spawned is not None
    assert spawned.id != task_id
    assert spawned.do_at is not None
    assert before + timedelta(hours=2) - timedelta(seconds=2) <= spawned.do_at
    assert spawned.do_at <= after + timedelta(hours=2) + timedelta(seconds=2)


def test_in_flight_excludes_future_do_at(_test_db):
    Session = _test_db
    future = datetime.utcnow() + timedelta(hours=1)
    past = datetime.utcnow() - timedelta(minutes=1)

    with Session() as s:
        future_chat = ChatSession()
        s.add(future_chat)
        s.flush()
        s.add(
            Task(
                title="Sleeping",
                assignee="assistant",
                chat_session_id=future_chat.id,
                do_at=future,
            )
        )

        past_chat = ChatSession()
        s.add(past_chat)
        s.flush()
        s.add(
            Task(
                title="Awake",
                assignee="assistant",
                chat_session_id=past_chat.id,
                do_at=past,
            )
        )

        no_due_chat = ChatSession()
        s.add(no_due_chat)
        s.flush()
        s.add(
            Task(
                title="Always",
                assignee="assistant",
                chat_session_id=no_due_chat.id,
            )
        )
        s.commit()
        future_chat_id = future_chat.id
        past_chat_id = past_chat.id
        no_due_chat_id = no_due_chat.id

    flight = [t.chat_session_id for t in runner.list_in_flight_tasks()]
    assert future_chat_id not in flight
    assert past_chat_id in flight
    assert no_due_chat_id in flight


@pytest.fixture
def core_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "core"
    root.mkdir()
    import app.config as config_mod
    from app.knowledge import core as core_mod

    monkeypatch.setattr(config_mod, "CORE_DIR", root, raising=True)
    monkeypatch.setattr(core_mod, "CORE_DIR", root, raising=True)
    return root


def test_save_core_memory_writes_about_user(core_root: Path):
    from app.agent.tools.knowledge import do_save_core_memory

    result = do_save_core_memory("about_user", "Lives in Berlin.\n")
    assert result == {"ok": True, "name": "about_user"}
    assert (core_root / "about_user.md").read_text() == "Lives in Berlin.\n"


def test_save_core_memory_writes_behavior(core_root: Path):
    from app.agent.tools.knowledge import do_save_core_memory

    result = do_save_core_memory("behavior", "Be terse.\n")
    assert result["ok"] is True
    assert (core_root / "behavior.md").read_text() == "Be terse.\n"


def test_save_core_memory_rejects_unknown_name(core_root: Path):
    from app.agent.tools.knowledge import do_save_core_memory

    result = do_save_core_memory("evil", "nope")
    assert "error" in result
    assert "unknown core memory file" in result["error"]
    assert not list(core_root.iterdir())
