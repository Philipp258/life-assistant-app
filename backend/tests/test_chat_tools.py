"""Tests for the agent's chat-reading and choice tools."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.agent.tools.chats import (
    do_ask_user_choice,
    do_list_chat_messages,
    do_read_main_chat_recent,
)
from app.chat.service import get_or_create_main_session
from app.chat.models import ChatSession
from tests._message_factory import make_message
from app.tasks.models import Task


def _seed_message(
    Session,
    session_id: int,
    *,
    kind: str,
    parts: list[dict],
    created_at: datetime | None = None,
) -> int:
    with Session() as s:
        row = make_message(
            session_id=session_id,
            kind=kind,
            parts_json={"kind": kind, "parts": parts},
        )
        if created_at is not None:
            row.created_at = created_at
        s.add(row)
        s.commit()
        return row.id


def _make_session(Session) -> int:
    with Session() as s:
        chat = ChatSession()
        s.add(chat)
        s.commit()
        return chat.id


def test_list_chat_messages_renders_text_and_tools(_test_db):
    Session = _test_db
    sid = _make_session(Session)
    _seed_message(
        Session,
        sid,
        kind="request",
        parts=[{"part_kind": "user-prompt", "content": "hello"}],
    )
    _seed_message(
        Session,
        sid,
        kind="response",
        parts=[
            {"part_kind": "text", "content": "hi"},
            {
                "part_kind": "tool-call",
                "tool_name": "get_task",
                "args": '{"task_id": 1}',
            },
        ],
    )
    _seed_message(
        Session,
        sid,
        kind="request",
        parts=[
            {
                "part_kind": "tool-return",
                "tool_name": "get_task",
                "content": "task body here",
            }
        ],
    )

    out = do_list_chat_messages(sid)
    msgs = out["messages"]
    assert out["total"] == 3
    assert out["has_more"] is False
    assert out["next_offset"] is None
    assert len(msgs) == 3
    assert msgs[0]["role"] == "user"
    assert msgs[0]["text"] == "hello"
    assert msgs[1]["role"] == "assistant"
    assert "hi" in msgs[1]["text"]
    assert "Internal tool call recorded: get_task" in msgs[1]["text"]
    assert "<tool_call:" not in msgs[1]["text"]
    assert msgs[2]["role"] == "tool"
    assert "Internal tool result recorded: get_task" in msgs[2]["text"]
    assert "<tool_return:" not in msgs[2]["text"]


def test_list_chat_messages_unknown_session(_test_db):
    out = do_list_chat_messages(99999)
    assert isinstance(out, dict)
    assert "error" in out


def test_list_chat_messages_since_filter(_test_db):
    Session = _test_db
    sid = _make_session(Session)
    old = datetime.utcnow() - timedelta(hours=2)
    new = datetime.utcnow()
    _seed_message(
        Session,
        sid,
        kind="request",
        parts=[{"part_kind": "user-prompt", "content": "old"}],
        created_at=old,
    )
    _seed_message(
        Session,
        sid,
        kind="request",
        parts=[{"part_kind": "user-prompt", "content": "new"}],
        created_at=new,
    )
    cutoff = datetime.utcnow() - timedelta(hours=1)
    out = do_list_chat_messages(sid, since=cutoff)
    assert [m["text"] for m in out["messages"]] == ["new"]
    assert out["total"] == 1


def test_list_chat_messages_since_accepts_offset_aware_datetime(_test_db):
    """Regression: pydantic-ai parses ISO timestamps with `Z` / offset
    as timezone-aware datetimes. The DB stores naive UTC, so we must
    normalize at the tool boundary or the comparison crashes."""
    from datetime import UTC

    Session = _test_db
    sid = _make_session(Session)
    old = datetime.utcnow() - timedelta(hours=2)
    new = datetime.utcnow()
    _seed_message(
        Session,
        sid,
        kind="request",
        parts=[{"part_kind": "user-prompt", "content": "old"}],
        created_at=old,
    )
    _seed_message(
        Session,
        sid,
        kind="request",
        parts=[{"part_kind": "user-prompt", "content": "new"}],
        created_at=new,
    )
    cutoff_aware = datetime.now(UTC) - timedelta(hours=1)
    out = do_list_chat_messages(sid, since=cutoff_aware)
    assert [m["text"] for m in out["messages"]] == ["new"]


def test_list_chat_messages_limit(_test_db):
    Session = _test_db
    sid = _make_session(Session)
    for i in range(5):
        _seed_message(
            Session,
            sid,
            kind="request",
            parts=[{"part_kind": "user-prompt", "content": f"m{i}"}],
        )
    out = do_list_chat_messages(sid, limit=2)
    assert len(out["messages"]) == 2
    assert [m["text"] for m in out["messages"]] == ["m0", "m1"]
    assert out["total"] == 5
    assert out["has_more"] is True
    assert out["next_offset"] == 2

    page2 = do_list_chat_messages(sid, limit=2, offset=2)
    assert [m["text"] for m in page2["messages"]] == ["m2", "m3"]
    assert page2["next_offset"] == 4

    last = do_list_chat_messages(sid, limit=2, offset=4)
    assert [m["text"] for m in last["messages"]] == ["m4"]
    assert last["has_more"] is False
    assert last["next_offset"] is None


def test_list_chat_messages_truncates_long_tool_returns(_test_db):
    Session = _test_db
    sid = _make_session(Session)
    long_blob = "x" * 1000
    _seed_message(
        Session,
        sid,
        kind="request",
        parts=[
            {
                "part_kind": "tool-return",
                "tool_name": "list_tasks",
                "content": long_blob,
            }
        ],
    )
    out = do_list_chat_messages(sid)
    first = out["messages"][0]
    assert len(first["text"]) < 500
    assert first["text"].endswith("…")


def test_read_main_chat_recent_pages_and_clamps(_test_db):
    Session = _test_db
    with Session() as s:
        sid = get_or_create_main_session(s).id

    for i in range(125):
        _seed_message(
            Session,
            sid,
            kind="request",
            parts=[{"part_kind": "user-prompt", "content": f"m{i}"}],
        )

    out = do_read_main_chat_recent(limit=1_000_000)

    assert out["total"] == 125
    assert out["limit"] == 100
    assert out["has_more"] is True
    assert out["next_offset"] == 100
    assert len(out["messages"]) == 100
    assert out["messages"][0]["text"] == "m25"
    assert out["messages"][-1]["text"] == "m124"

    older = do_read_main_chat_recent(limit=100, offset=100)
    assert older["has_more"] is False
    assert [m["text"] for m in older["messages"]] == [f"m{i}" for i in range(25)]


def test_ask_user_choice_reassigns_to_user(_test_db):
    Session = _test_db
    with Session() as s:
        chat = ChatSession()
        s.add(chat)
        s.flush()
        task = Task(
            title="Reflecting",
            chat_session_id=chat.id,
            assignee="assistant",
        )
        s.add(task)
        s.flush()
        chat.task_id = task.id
        s.commit()
        task_id = task.id

    out = do_ask_user_choice(
        task_id,
        question="Save this as a hard rule or a preference?",
        options=["Hard rule", "Preference", "Skip"],
    )
    assert out["ok"] is True
    assert out["asked"].startswith("Save this")
    assert out["options"] == ["Hard rule", "Preference", "Skip"]
    assert out["allow_free_text"] is True

    with Session() as s:
        task = s.get(Task, task_id)
        assert task is not None
        assert task.assignee == "user"


def test_ask_user_choice_validates_option_count(_test_db):
    out = do_ask_user_choice(1, "?", options=["only one"])
    assert "error" in out

    seven = [f"opt{i}" for i in range(7)]
    out = do_ask_user_choice(1, "?", options=seven)
    assert "error" in out


def test_ask_user_choice_unknown_task(_test_db):
    out = do_ask_user_choice(99999, "?", options=["a", "b"])
    assert "error" in out
