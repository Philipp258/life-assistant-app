"""Token-aware main-chat compaction.

Covers grouping (tool-call/return atomicity), token estimation, the
compaction decision (under/over threshold), summarizer integration, and
the service-level loader that persists compacted_at + the summary row.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    ModelMessagesTypeAdapter,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from app.chat import compaction
from app.chat.models import ChatSession, Message
from tests._message_factory import make_message
from app.chat.service import (
    aload_compacted_history,
    aload_compacted_history_with_cursor,
    get_or_create_main_session,
    load_main_session_as_ui_messages,
    load_compacted_history,
    save_new_messages,
)
from app.tasks.models import Task


# ---------- helpers ----------


def _user(text: str) -> ModelRequest:
    return ModelRequest(parts=[UserPromptPart(content=text)])


def _assistant(text: str) -> ModelResponse:
    return ModelResponse(parts=[TextPart(content=text)])


def _insert_message(Session, session_id: int, message, created_at: datetime) -> int:
    blob = ModelMessagesTypeAdapter.dump_python([message], mode="json")[0]
    with Session() as s:
        row = make_message(
            session_id=session_id,
            kind=blob.get("kind", "request"),
            parts_json=blob,
            created_at=created_at,
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        return row.id


def _tool_call(name: str, args: dict, call_id: str) -> ModelResponse:
    return ModelResponse(parts=[ToolCallPart(tool_name=name, args=args, tool_call_id=call_id)])


def _tool_return(name: str, content: str, call_id: str) -> ModelRequest:
    return ModelRequest(
        parts=[ToolReturnPart(tool_name=name, content=content, tool_call_id=call_id)]
    )


# ---------- estimate_tokens ----------


def test_estimate_tokens_scales_with_text_length():
    short = compaction.estimate_tokens([_user("hi")])
    long = compaction.estimate_tokens([_user("x" * 4000)])
    assert long > short
    # 4000 chars at 4 chars/token ≈ 1000 tokens, plus overhead.
    assert long >= 1000


def test_estimate_tokens_counts_tool_parts():
    msgs = [
        _tool_call("bash", {"command": "ls"}, "c1"),
        _tool_return("bash", "file1\nfile2\nfile3", "c1"),
    ]
    assert compaction.estimate_tokens(msgs) > 0


# ---------- group_messages ----------


def test_group_messages_pairs_tool_call_with_return():
    msgs = [
        _user("run ls"),
        _tool_call("bash", {"command": "ls"}, "c1"),
        _tool_return("bash", "out", "c1"),
        _assistant("done"),
    ]
    groups = compaction.group_messages(msgs)
    assert [g.kind for g in groups] == ["user", "tool_exchange", "assistant_text"]
    # Tool-call + tool-return must live in the same group.
    assert len(groups[1].messages) == 2


def test_group_messages_handles_multiple_tool_calls_in_one_response():
    msgs = [
        _user("multi"),
        ModelResponse(
            parts=[
                ToolCallPart(tool_name="a", args={}, tool_call_id="c1"),
                ToolCallPart(tool_name="b", args={}, tool_call_id="c2"),
            ]
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(tool_name="a", content="ra", tool_call_id="c1"),
                ToolReturnPart(tool_name="b", content="rb", tool_call_id="c2"),
            ]
        ),
        _assistant("done"),
    ]
    groups = compaction.group_messages(msgs)
    assert [g.kind for g in groups] == ["user", "tool_exchange", "assistant_text"]
    assert len(groups[1].messages) == 2


def test_group_messages_handles_returns_split_across_requests():
    """If a tool exchange's returns arrive in multiple ModelRequests,
    we keep extending the group until every pending id is closed."""
    msgs = [
        ModelResponse(
            parts=[
                ToolCallPart(tool_name="a", args={}, tool_call_id="c1"),
                ToolCallPart(tool_name="b", args={}, tool_call_id="c2"),
            ]
        ),
        _tool_return("a", "ra", "c1"),
        _tool_return("b", "rb", "c2"),
    ]
    groups = compaction.group_messages(msgs)
    assert len(groups) == 1
    assert groups[0].kind == "tool_exchange"
    assert len(groups[0].messages) == 3


# ---------- compact ----------


def test_compact_noop_under_threshold():
    msgs = [_user("hi"), _assistant("hello")]
    result = compaction.compact(
        msgs,
        trigger_tokens=10_000,
        keep_groups=4,
        summarizer=lambda _: "should not be called",
    )
    assert result.did_compact is False
    assert result.summary_message is None
    assert result.kept_messages == msgs
    assert result.compacted_messages == []


def test_compact_summarizes_and_keeps_recent():
    # Build 10 alternating user/assistant turns (= 10 groups).
    msgs = []
    for i in range(10):
        msgs.append(_user(f"u{i} " + "x" * 1000))
        msgs.append(_assistant(f"a{i} " + "y" * 1000))

    captured: dict[str, str] = {}

    def fake_summarizer(text: str) -> str:
        captured["text"] = text
        return "SUMMARY GOES HERE"

    result = compaction.compact(
        msgs,
        trigger_tokens=1000,
        keep_groups=4,
        summarizer=fake_summarizer,
    )
    assert result.did_compact is True
    assert result.summary_message is not None
    # 10 user + 10 assistant = 20 groups; keep last 4 → compact 16.
    assert len(result.kept_messages) == 4
    assert len(result.compacted_messages) == 16
    # Summarizer received rendered text containing some of the compacted content.
    assert "u0" in captured["text"]
    assert "a0" in captured["text"]
    # And NOT the recent kept content.
    assert "u9" not in captured["text"]


def test_compact_preserves_tool_exchange_atomicity():
    """A tool-call/return pair at the cutoff must not be split."""
    # Build groups: 5 plain user/assistant pairs, then a tool exchange,
    # then more pairs. With keep_groups=2, the tool exchange should
    # land entirely in either the kept side or the compacted side —
    # never have its call separated from its return.
    msgs = []
    for i in range(5):
        msgs.append(_user(f"u{i} " + "x" * 500))
        msgs.append(_assistant(f"a{i} " + "y" * 500))
    msgs.append(_tool_call("bash", {"cmd": "ls"}, "c1"))
    msgs.append(_tool_return("bash", "out", "c1"))
    for i in range(3):
        msgs.append(_user(f"v{i} " + "x" * 500))
        msgs.append(_assistant(f"b{i} " + "y" * 500))

    result = compaction.compact(
        msgs,
        trigger_tokens=500,
        keep_groups=4,
        summarizer=lambda _: "S",
    )
    assert result.did_compact is True
    # No kept message should be a stray ToolReturnPart with no preceding
    # ToolCallPart (i.e. balanced tool ids).
    pending: set[str] = set()
    for m in result.kept_messages:
        for p in m.parts or []:
            if isinstance(p, ToolCallPart):
                pending.add(p.tool_call_id)
            elif isinstance(p, ToolReturnPart):
                # Must close a pending call from within the kept slice.
                assert p.tool_call_id in pending
                pending.discard(p.tool_call_id)
    assert not pending


def test_compact_summary_message_is_a_modelrequest_with_user_prompt():
    msgs = [_user("u" + "x" * 5000), _assistant("a" + "y" * 5000)] * 5
    result = compaction.compact(
        msgs,
        trigger_tokens=100,
        keep_groups=2,
        summarizer=lambda _: "RECAP",
    )
    assert result.did_compact
    assert isinstance(result.summary_message, ModelRequest)
    parts = result.summary_message.parts
    assert len(parts) == 1
    assert isinstance(parts[0], UserPromptPart)
    assert "RECAP" in parts[0].content
    assert "<conversation_summary>" in parts[0].content


def test_compact_punts_when_recent_groups_alone_exceed_threshold():
    # Two huge groups, keep_groups=4 → can't drop anything.
    msgs = [_user("x" * 100_000), _assistant("y" * 100_000)]
    result = compaction.compact(
        msgs,
        trigger_tokens=1000,
        keep_groups=4,
        summarizer=lambda _: "should not run",
    )
    assert result.did_compact is False
    assert result.kept_messages == msgs


# ---------- messages_to_text ----------


def test_messages_to_text_truncates_tool_output():
    huge = "z" * 10_000
    msgs = [
        _user("run"),
        _tool_call("bash", {"cmd": "cat big"}, "c1"),
        _tool_return("bash", huge, "c1"),
    ]
    rendered = compaction.messages_to_text(msgs, tool_output_truncate=200)
    # Truncated body present, original full string is not.
    assert huge not in rendered
    assert "Tool return" in rendered


# ---------- service.load_compacted_history ----------


def test_load_compacted_history_noop_under_threshold(_test_db, monkeypatch):
    Session = _test_db
    with Session() as s:
        main = get_or_create_main_session(s)
        save_new_messages(s, main.id, [_user("hi"), _assistant("hello")])

    # Trigger is huge, nothing compacts.
    from app.config import settings

    monkeypatch.setattr(settings, "compaction_trigger_tokens", 1_000_000, raising=True)

    with Session() as s:
        msgs = load_compacted_history(s, main.id)
    assert len(msgs) == 2

    with Session() as s:
        rows = s.query(Message).filter(Message.session_id == main.id).all()
        assert all(r.compacted_at is None for r in rows)
        assert len(rows) == 2


def test_load_compacted_history_persists_summary_and_marks_old_rows(_test_db, monkeypatch):
    Session = _test_db
    with Session() as s:
        main = get_or_create_main_session(s)
        # 10 turns × ~2KB each → comfortably over the test threshold.
        msgs = []
        for i in range(10):
            msgs.append(_user(f"u{i} " + "x" * 1000))
            msgs.append(_assistant(f"a{i} " + "y" * 1000))
        save_new_messages(s, main.id, msgs)
        original_count = s.query(Message).filter(Message.session_id == main.id).count()

    from app.config import settings

    monkeypatch.setattr(settings, "compaction_trigger_tokens", 500, raising=True)
    monkeypatch.setattr(settings, "compaction_keep_groups", 4, raising=True)

    with Session() as s:
        result = load_compacted_history(s, main.id, summarizer=lambda _: "compacted summary")

    # Summary + last 4 kept groups (4 messages, alternating).
    assert len(result) == 1 + 4
    assert isinstance(result[0], ModelRequest)
    assert isinstance(result[0].parts[0], UserPromptPart)
    assert "compacted summary" in result[0].parts[0].content

    with Session() as s:
        rows = s.query(Message).filter(Message.session_id == main.id).order_by(Message.id).all()
        # Original rows + 1 newly persisted summary row.
        assert len(rows) == original_count + 1
        # The first 16 are stamped compacted.
        compacted = [r for r in rows if r.compacted_at is not None]
        assert len(compacted) == 16
        # Summary row is the most recent and not itself compacted.
        assert rows[-1].compacted_at is None


def test_load_compacted_history_uses_created_at_order_when_row_ids_diverge(_test_db, monkeypatch):
    """Main-chat compaction must follow conversation time, not DB row id.

    This covers restored/legacy histories where rows can be inserted in
    role batches even though `created_at` has the real chronology.
    """
    Session = _test_db
    with Session() as s:
        main = get_or_create_main_session(s)
        main_id = main.id

    base = datetime(2026, 5, 17, 9, 0, 0)
    user_ids = [
        _insert_message(
            Session, main_id, _user(f"u{i} " + "x" * 1000), base + timedelta(minutes=2 * i)
        )
        for i in range(6)
    ]
    assistant_ids = [
        _insert_message(
            Session,
            main_id,
            _assistant(f"a{i} " + "y" * 1000),
            base + timedelta(minutes=2 * i + 1),
        )
        for i in range(6)
    ]
    assert user_ids + assistant_ids == sorted(user_ids + assistant_ids)

    from app.config import settings

    monkeypatch.setattr(settings, "compaction_trigger_tokens", 500, raising=True)
    monkeypatch.setattr(settings, "compaction_keep_groups", 2, raising=True)

    captured: dict[str, str] = {}

    def summarizer(text: str) -> str:
        captured["text"] = text
        return "ordered summary"

    with Session() as s:
        result = load_compacted_history(s, main_id, summarizer=summarizer)

    assert len(result) == 3
    assert "u0" in captured["text"]
    assert "a0" in captured["text"]
    assert "u4" in captured["text"]
    assert "a4" in captured["text"]
    assert "u5" not in captured["text"]
    assert "a5" not in captured["text"]
    assert result[1].parts[0].content.startswith("u5")
    assert result[2].parts[0].content.startswith("a5")

    with Session() as s:
        compacted_ids = [
            row.id
            for row in s.query(Message)
            .filter(Message.session_id == main_id, Message.compacted_at.isnot(None))
            .order_by(Message.created_at, Message.id)
            .all()
        ]
    assert compacted_ids == [
        user_ids[0],
        assistant_ids[0],
        user_ids[1],
        assistant_ids[1],
        user_ids[2],
        assistant_ids[2],
        user_ids[3],
        assistant_ids[3],
        user_ids[4],
        assistant_ids[4],
    ]


def test_load_compacted_history_skips_already_compacted_rows(_test_db, monkeypatch):
    """A second call should noop — only the live tail + summary remain."""
    Session = _test_db
    with Session() as s:
        main = get_or_create_main_session(s)
        msgs = []
        for i in range(10):
            msgs.append(_user(f"u{i} " + "x" * 1000))
            msgs.append(_assistant(f"a{i} " + "y" * 1000))
        save_new_messages(s, main.id, msgs)

    from app.config import settings

    monkeypatch.setattr(settings, "compaction_trigger_tokens", 500, raising=True)
    monkeypatch.setattr(settings, "compaction_keep_groups", 4, raising=True)

    summarizer_calls = {"n": 0}

    def summarizer(_text: str) -> str:
        summarizer_calls["n"] += 1
        return "S"

    # Boost threshold high enough that the second call sits under it.
    with Session() as s:
        load_compacted_history(s, main.id, summarizer=summarizer)
    monkeypatch.setattr(settings, "compaction_trigger_tokens", 1_000_000, raising=True)
    with Session() as s:
        msgs2 = load_compacted_history(s, main.id, summarizer=summarizer)

    assert summarizer_calls["n"] == 1  # second call did not summarize again
    # 1 summary + 4 kept messages from first compaction
    assert len(msgs2) == 5
    assert isinstance(msgs2[0], ModelRequest)
    assert isinstance(msgs2[0].parts[0], UserPromptPart)
    assert msgs2[0].parts[0].content.startswith("<conversation_summary>")
    assert any(
        "u8" in p.content for m in msgs2[1:] for p in m.parts if isinstance(p, UserPromptPart)
    )


def test_compaction_summary_is_hidden_from_ui_history(_test_db, monkeypatch):
    Session = _test_db
    with Session() as s:
        main = get_or_create_main_session(s)
        msgs = []
        for i in range(10):
            msgs.append(_user(f"u{i} " + "x" * 1000))
            msgs.append(_assistant(f"a{i} " + "y" * 1000))
        save_new_messages(s, main.id, msgs)

    from app.config import settings

    monkeypatch.setattr(settings, "compaction_trigger_tokens", 500, raising=True)
    monkeypatch.setattr(settings, "compaction_keep_groups", 4, raising=True)

    with Session() as s:
        load_compacted_history(s, main.id, summarizer=lambda _: "internal summary")
    with Session() as s:
        _sid, ui_messages = load_main_session_as_ui_messages(s)

    dumped = json.dumps(ui_messages)
    assert "<conversation_summary>" not in dumped
    assert "internal summary" not in dumped
    # The original scrollback remains visible even though the agent uses
    # the hidden compacted summary as context.
    assert "u0" in dumped


# ---------- async path (acompact / aload_compacted_history) ----------


def test_acompact_accepts_async_summarizer():
    """The router uses `acompact` so the LLM round trip can be awaited
    instead of blocking the FastAPI event loop on `Agent.run_sync()`."""
    msgs = [_user("u" + "x" * 5000), _assistant("a" + "y" * 5000)] * 5

    async def async_summarizer(text: str) -> str:
        await asyncio.sleep(0)  # actually a coroutine
        return "ASYNC RECAP"

    result = asyncio.run(
        compaction.acompact(
            msgs,
            trigger_tokens=100,
            keep_groups=2,
            summarizer=async_summarizer,
        )
    )
    assert result.did_compact
    assert "ASYNC RECAP" in result.summary_message.parts[0].content


def test_acompact_accepts_sync_summarizer():
    """Sync summarizers still work — `acompact` only awaits when the
    callable returns an awaitable. Lets tests share fakes between paths.
    """
    msgs = [_user("u" + "x" * 5000), _assistant("a" + "y" * 5000)] * 5

    result = asyncio.run(
        compaction.acompact(
            msgs,
            trigger_tokens=100,
            keep_groups=2,
            summarizer=lambda _: "SYNC RECAP",
        )
    )
    assert result.did_compact
    assert "SYNC RECAP" in result.summary_message.parts[0].content


def test_aload_compacted_history_persists_summary_and_marks_old_rows(_test_db, monkeypatch):
    """End-to-end check on the async loader the router actually uses."""
    Session = _test_db
    with Session() as s:
        main = get_or_create_main_session(s)
        msgs = []
        for i in range(10):
            msgs.append(_user(f"u{i} " + "x" * 1000))
            msgs.append(_assistant(f"a{i} " + "y" * 1000))
        save_new_messages(s, main.id, msgs)
        original_count = s.query(Message).filter(Message.session_id == main.id).count()

    from app.config import settings

    monkeypatch.setattr(settings, "compaction_trigger_tokens", 500, raising=True)
    monkeypatch.setattr(settings, "compaction_keep_groups", 4, raising=True)

    async def async_summarizer(_text: str) -> str:
        return "async summary"

    with Session() as s:
        result = asyncio.run(aload_compacted_history(s, main.id, summarizer=async_summarizer))

    assert len(result) == 1 + 4
    assert "async summary" in result[0].parts[0].content

    with Session() as s:
        rows = s.query(Message).filter(Message.session_id == main.id).order_by(Message.id).all()
        assert len(rows) == original_count + 1
        compacted = [r for r in rows if r.compacted_at is not None]
        assert len(compacted) == 16
        assert rows[-1].compacted_at is None


def test_aload_compacted_history_with_cursor_compacts_task_chat(_test_db, monkeypatch):
    Session = _test_db
    with Session() as s:
        chat = ChatSession()
        s.add(chat)
        s.flush()
        task = Task(title="Long task", chat_session_id=chat.id, assignee="assistant")
        s.add(task)
        s.flush()
        chat.task_id = task.id
        msgs = []
        for i in range(10):
            msgs.append(_user(f"u{i} " + "x" * 1000))
            msgs.append(_assistant(f"a{i} " + "y" * 1000))
        save_new_messages(s, chat.id, msgs)
        session_id = chat.id

    from app.config import settings

    monkeypatch.setattr(settings, "compaction_trigger_tokens", 500, raising=True)
    monkeypatch.setattr(settings, "compaction_keep_groups", 4, raising=True)

    with Session() as s:
        result, cursor = asyncio.run(
            aload_compacted_history_with_cursor(s, session_id, summarizer=lambda _: "task summary")
        )

    assert len(result) == 1 + 4
    assert "task summary" in result[0].parts[0].content

    with Session() as s:
        rows = s.query(Message).filter(Message.session_id == session_id).order_by(Message.id).all()
        assert cursor == rows[-1].id
        assert rows[-1].compacted_at is None
        assert sum(1 for row in rows if row.compacted_at is not None) == 16
