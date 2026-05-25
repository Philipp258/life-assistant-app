from __future__ import annotations

from datetime import datetime, timedelta

from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from app.chat.models import ChatSession, Message
from app.chat.service import (
    get_or_create_main_session,
    load_compacted_history,
    load_session_as_ui_messages,
    save_new_messages,
)


def _new_session(Session) -> int:
    with Session() as s:
        chat = ChatSession()
        s.add(chat)
        s.commit()
        s.refresh(chat)
        return chat.id


def test_snapshot_ids_are_stable_db_row_ids(_test_db):
    sid = _new_session(_test_db)
    with _test_db() as s:
        save_new_messages(
            s,
            sid,
            [
                ModelRequest(parts=[UserPromptPart(content="hello")]),
                ModelResponse(parts=[TextPart(content="hi back")]),
            ],
        )
        rows = s.query(Message).filter(Message.session_id == sid).order_by(Message.id).all()
        row_ids = [str(row.id) for row in rows]

    with _test_db() as s:
        first = load_session_as_ui_messages(s, sid)
    with _test_db() as s:
        second = load_session_as_ui_messages(s, sid)

    assert [m["id"] for m in first] == row_ids
    assert [m["id"] for m in first] == [m["id"] for m in second]


def test_interleaved_tool_turn_aligns_response_rows(_test_db):
    sid = _new_session(_test_db)
    with _test_db() as s:
        save_new_messages(
            s,
            sid,
            [
                ModelRequest(parts=[UserPromptPart(content="do the thing")]),
                ModelResponse(
                    parts=[
                        TextPart(content="working"),
                        ToolCallPart(tool_name="x", args={}, tool_call_id="c1"),
                    ]
                ),
                ModelRequest(
                    parts=[ToolReturnPart(tool_name="x", tool_call_id="c1", content="done")]
                ),
                ModelResponse(parts=[TextPart(content="finished")]),
            ],
        )
        rows = s.query(Message).filter(Message.session_id == sid).order_by(Message.id).all()

    request_row = next(row for row in rows if row.kind == "request")
    response_rows = [row for row in rows if row.kind == "response"]

    with _test_db() as s:
        ui = load_session_as_ui_messages(s, sid)

    users = [m for m in ui if m["role"] == "user"]
    assistants = [m for m in ui if m["role"] == "assistant"]
    assert [m["id"] for m in users] == [str(request_row.id)]
    assert [m["id"] for m in assistants] == [str(row.id) for row in response_rows]


def _insert_message(Session, sid: int, message: ModelMessage, created_at: datetime) -> int:
    blob = ModelMessagesTypeAdapter.dump_python([message], mode="json")[0]
    with Session() as s:
        row = Message(
            session_id=sid,
            kind=blob.get("kind", "request"),
            parts_json=blob,
            created_at=created_at,
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        return row.id


def test_ui_messages_follow_created_at_not_role_or_row_id(_test_db):
    sid = _new_session(_test_db)
    base = datetime(2026, 5, 17, 12, 0, 0)

    # Insert user rows first and assistant rows second to reproduce the
    # grouped-by-role row id shape seen in the main chat bug.
    u1 = _insert_message(
        _test_db,
        sid,
        ModelRequest(parts=[UserPromptPart(content="first user")]),
        base,
    )
    u2 = _insert_message(
        _test_db,
        sid,
        ModelRequest(parts=[UserPromptPart(content="second user")]),
        base + timedelta(minutes=2),
    )
    a1 = _insert_message(
        _test_db,
        sid,
        ModelResponse(parts=[TextPart(content="first assistant")]),
        base + timedelta(minutes=1),
    )
    a2 = _insert_message(
        _test_db,
        sid,
        ModelResponse(parts=[TextPart(content="second assistant")]),
        base + timedelta(minutes=3),
    )

    assert [u1, u2, a1, a2] == sorted([u1, u2, a1, a2])

    with _test_db() as s:
        ui = load_session_as_ui_messages(s, sid)

    assert [(m["role"], m["id"]) for m in ui] == [
        ("user", str(u1)),
        ("assistant", str(a1)),
        ("user", str(u2)),
        ("assistant", str(a2)),
    ]
    assert [m["createdAt"] for m in ui] == [
        "2026-05-17T12:00:00Z",
        "2026-05-17T12:01:00Z",
        "2026-05-17T12:02:00Z",
        "2026-05-17T12:03:00Z",
    ]


def test_compacted_then_live_history_stays_chronological(_test_db, monkeypatch):
    """Hypothesis: mixed compacted/live main-chat messages.

    After compaction, older rows are stamped `compacted_at` (still
    visible to the user) and a hidden `<conversation_summary>` row is
    persisted *after* them with a fresh, later id/timestamp. A
    subsequent live turn then appends newer rows. The UI must:

    - drop the summary row entirely,
    - keep the compacted (older) messages before the live (newer) ones,
    - stay chronological (no grouped-by-role inversion), and
    - carry a stable numeric DB row id + `createdAt` on every message.
    """
    from app.config import settings

    main_id = get_or_create_main_session(_test_db()).id
    base = datetime(2026, 5, 17, 9, 0, 0)

    # Insert ALL user rows first, then ALL assistant rows, but with
    # interleaved timestamps: row-id order is grouped-by-role while
    # `created_at` is the true conversational chronology. This is the
    # exact divergence the bug surfaced; under pure-id ordering the UI
    # would render all users then all assistants.
    user_ids = [
        _insert_message(
            _test_db,
            main_id,
            ModelRequest(parts=[UserPromptPart(content=f"old user {i}")]),
            base + timedelta(minutes=2 * i),
        )
        for i in range(6)
    ]
    assistant_ids = [
        _insert_message(
            _test_db,
            main_id,
            ModelResponse(parts=[TextPart(content=f"old assistant {i}")]),
            base + timedelta(minutes=2 * i + 1),
        )
        for i in range(6)
    ]
    assert sorted(user_ids + assistant_ids) == user_ids + assistant_ids  # grouped-by-role ids
    expected: list[tuple[str, str, str]] = []
    for i in range(6):
        expected.append(("user", str(user_ids[i]), f"old user {i}"))
        expected.append(("assistant", str(assistant_ids[i]), f"old assistant {i}"))

    monkeypatch.setattr(settings, "compaction_trigger_tokens", 1, raising=True)
    monkeypatch.setattr(settings, "compaction_keep_groups", 1, raising=True)
    with _test_db() as s:
        load_compacted_history(s, main_id, summarizer=lambda _t: "older context compacted")
        # The persisted summary row exists but must be hidden from the UI.
        assert any(
            isinstance(r.parts_json, dict)
            and "<conversation_summary>"
            in str((r.parts_json.get("parts") or [{}])[0].get("content", ""))
            for r in s.query(Message).filter(Message.session_id == main_id).all()
        )

    # A normal live turn after compaction (real func.now() timestamps,
    # strictly newer than the explicit pre-compaction ones).
    with _test_db() as s:
        save_new_messages(
            s,
            main_id,
            [
                ModelRequest(parts=[UserPromptPart(content="fresh user")]),
                ModelResponse(parts=[TextPart(content="fresh assistant")]),
            ],
        )

    with _test_db() as s:
        ui = load_session_as_ui_messages(s, main_id)

    def _text(m: dict) -> str:
        for p in m.get("parts", []):
            if p.get("type") == "text":
                return p.get("text", "")
        return ""

    # No summary leaked into the UI.
    assert all("<conversation_summary>" not in _text(m) for m in ui)
    # Compacted history first, in chronological order, then the live turn.
    assert [(m["role"], m["id"], _text(m)) for m in ui] == [
        *expected,
        ("user", ui[-2]["id"], "fresh user"),
        ("assistant", ui[-1]["id"], "fresh assistant"),
    ]
    # Every UI message carries a stable numeric row id + createdAt, and
    # the (createdAt, id) sequence is non-decreasing — the invariant the
    # frontend reconciler now sorts on.
    keys = [(m["createdAt"], int(m["id"])) for m in ui]
    assert all(m["createdAt"] for m in ui)
    assert keys == sorted(keys)
