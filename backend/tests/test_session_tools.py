"""Tests for the main → task relay.

`relay_to_task` is the one cross-session write: it resolves the task's
chat, stamps `source_session_id` on the persisted note, and flips the
task back to assignee='assistant' so the runner resumes it.
"""

from __future__ import annotations

from app.agent.tools.sessions import do_relay_to_task
from app.chat.models import ChatSession, Message
from app.tasks.models import Task


def _make_blocked_task(Session) -> tuple[int, int, int]:
    """Returns (source_session_id, task_id, task_chat_id)."""
    with Session() as s:
        source = ChatSession()
        chat = ChatSession()
        s.add_all([source, chat])
        s.flush()
        task = Task(
            title="Blocked task",
            assignee="user",
            chat_session_id=chat.id,
            is_done=False,
        )
        s.add(task)
        s.flush()
        chat.task_id = task.id
        s.commit()
        return source.id, task.id, chat.id


def test_relay_writes_task_chat_with_source_stamp_and_resumes(_test_db):
    Session = _test_db
    source_id, task_id, task_chat_id = _make_blocked_task(Session)

    result = do_relay_to_task(task_id, "user said: go ahead, 9-17 CET", source_session_id=source_id)
    assert result == {"ok": True, "task_id": task_id, "resumed": True}

    with Session() as s:
        rows = (
            s.query(Message).filter(Message.session_id == task_chat_id).order_by(Message.id).all()
        )
        task = s.get(Task, task_id)
    assert len(rows) == 1
    assert rows[0].source_session_id == source_id
    assert rows[0].role == "response"
    assert task.assignee == "assistant"  # resumed


def test_relay_unknown_task_returns_error(_test_db):
    result = do_relay_to_task(99999, "no task", source_session_id=None)
    assert "error" in result


def test_relay_empty_note_returns_error(_test_db):
    Session = _test_db
    _src, task_id, _chat = _make_blocked_task(Session)
    result = do_relay_to_task(task_id, "   ", source_session_id=None)
    assert "error" in result


def test_relay_into_own_task_chat_is_rejected(_test_db):
    Session = _test_db
    _src, task_id, task_chat_id = _make_blocked_task(Session)
    result = do_relay_to_task(task_id, "loop", source_session_id=task_chat_id)
    assert "error" in result
