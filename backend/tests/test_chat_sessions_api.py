"""Tests for the chat-session HTTP surface and in-process pubsub.

Phase 5: one persistent main session — `GET /api/chat/main`. REST is
initial-load only (`/chat/main`, `/chat/sessions/{id}/messages`); all
live traffic is the one WebSocket (`/api/ws`). No streaming POST, no
SSE.
"""

from __future__ import annotations

import asyncio

import pytest

from app.chat import pubsub


def test_main_returns_singleton(client):
    """`GET /api/chat/main` always returns a session_id, creating one if needed."""
    first = client.get("/api/chat/main").json()
    assert "session_id" in first
    assert first["messages"] == []
    second = client.get("/api/chat/main").json()
    assert second["session_id"] == first["session_id"]


def test_session_messages_404_for_unknown(client):
    r = client.get("/api/chat/sessions/99999/messages")
    assert r.status_code == 404


def test_session_messages_empty_history_for_main(client):
    sid = client.get("/api/chat/main").json()["session_id"]
    r = client.get(f"/api/chat/sessions/{sid}/messages")
    assert r.status_code == 200
    assert r.json() == {"session_id": sid, "messages": []}


def test_task_chat_session_resolves(client):
    """Creating a task auto-creates its task-bound session, reachable via /messages."""
    task = client.post("/api/tasks", json={"title": "T1"}).json()
    assert task["chat_session_id"] is not None
    r = client.get(f"/api/chat/sessions/{task['chat_session_id']}/messages")
    assert r.status_code == 200


@pytest.mark.usefixtures("_test_db")
def test_pubsub_delivers_to_subscribers():
    async def run():
        async with pubsub.subscribe(42) as q:
            pubsub.publish(42, {"type": "message", "n": 1})
            pubsub.publish(42, {"type": "message", "n": 2})
            first = await asyncio.wait_for(q.get(), timeout=1.0)
            second = await asyncio.wait_for(q.get(), timeout=1.0)
            assert first["n"] == 1
            assert second["n"] == 2

    asyncio.run(run())


@pytest.mark.usefixtures("_test_db")
def test_pubsub_isolated_by_session_id():
    async def run():
        async with pubsub.subscribe(1) as q1, pubsub.subscribe(2) as q2:
            pubsub.publish(1, {"hello": "one"})
            pubsub.publish(2, {"hello": "two"})
            assert (await asyncio.wait_for(q1.get(), timeout=1.0))["hello"] == "one"
            assert (await asyncio.wait_for(q2.get(), timeout=1.0))["hello"] == "two"

    asyncio.run(run())


@pytest.mark.usefixtures("_test_db")
def test_pubsub_no_subscriber_drops_silently():
    pubsub.publish(999, {"type": "message"})
    # nothing to assert — just verifying no exception escapes


def test_ws_requires_authenticated_session(unauthed_client):
    """The WS upgrade bypasses the HTTP auth middleware, so the handler
    must close an unauthenticated connection itself (code 4401)."""
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc:
        with unauthed_client.websocket_connect("/api/ws") as ws:
            ws.receive_json()
    assert exc.value.code == 4401


def test_ws_input_unknown_session_does_not_crash(client):
    """An `input` for a non-existent session is a no-op — no turn, no
    crash, the socket stays usable."""
    with client.websocket_connect("/api/ws") as ws:
        ws.send_json({"type": "subscribe", "session_ids": [99999]})
        snap = ws.receive_json()
        assert snap["type"] == "snapshot"
        assert snap["session_id"] == 99999
        assert snap["messages"] == []
        ws.send_json({"type": "input", "session_id": 99999, "text": "hello"})
        # Still alive: a resync round-trips.
        ws.send_json({"type": "resync", "session_id": 99999})
        again = ws.receive_json()
        assert again["type"] == "snapshot"


def test_save_run_messages_targets_explicit_session(_test_db):
    """`save_run_messages(session_id=X)` writes to X."""
    from pydantic_ai.messages import ModelRequest, UserPromptPart

    from app.chat.models import ChatSession, Message
    from app.chat.service import save_run_messages

    Session = _test_db
    with Session() as s:
        a = ChatSession()
        target = ChatSession()
        s.add_all([a, target])
        s.commit()
        s.refresh(a)
        s.refresh(target)
        target_id = target.id
        other_id = a.id

    msg = ModelRequest(parts=[UserPromptPart(content="hello")])
    with Session() as s:
        save_run_messages(s, [msg], session_id=target_id)

    with Session() as s:
        in_target = s.query(Message).filter(Message.session_id == target_id).count()
        in_other = s.query(Message).filter(Message.session_id == other_id).count()
    assert in_target == 1
    assert in_other == 0


def test_save_new_messages_publish_flag_controls_fanout(_test_db):
    """`publish=False` persists the row but skips the pubsub poke.

    Used by hidden writes (handoffs, compaction summaries) that must not
    nudge the channel; a normal visible write publishes a keyed row
    update.
    """
    from pydantic_ai.messages import ModelRequest, UserPromptPart

    from app.chat.models import ChatSession, Message
    from app.chat.service import save_new_messages

    Session = _test_db
    with Session() as s:
        chat = ChatSession()
        s.add(chat)
        s.commit()
        s.refresh(chat)
        sid = chat.id

    async def run():
        async with pubsub.subscribe(sid) as q:
            with Session() as s:
                save_new_messages(
                    s,
                    sid,
                    [ModelRequest(parts=[UserPromptPart(content="silent")])],
                    publish=False,
                )
            assert q.empty()

            with Session() as s:
                save_new_messages(
                    s,
                    sid,
                    [ModelRequest(parts=[UserPromptPart(content="loud")])],
                )
            event = await asyncio.wait_for(q.get(), timeout=1.0)
            assert event["type"] == "message_upsert"

    asyncio.run(run())

    with Session() as s:
        assert s.query(Message).filter(Message.session_id == sid).count() == 2


def test_session_messages_strip_system_prompt(_test_db):
    """Hydrated UI messages must not include the system-prompt entry.

    Regression: the system prompt was rendering as an assistant bubble
    after page refresh because VercelAI's adapter emits a `role: system`
    UIMessage from `SystemPromptPart`.
    """
    from pydantic_ai.messages import (
        ModelRequest,
        SystemPromptPart,
        UserPromptPart,
    )

    from app.chat.models import ChatSession
    from app.chat.service import load_session_as_ui_messages, save_new_messages

    Session = _test_db
    with Session() as s:
        chat = ChatSession()
        s.add(chat)
        s.commit()
        s.refresh(chat)
        sid = chat.id

    msg = ModelRequest(
        parts=[
            SystemPromptPart(content="you are a helpful nix"),
            UserPromptPart(content="hi"),
        ]
    )
    with Session() as s:
        save_new_messages(s, sid, [msg])

    with Session() as s:
        ui_messages = load_session_as_ui_messages(s, sid)

    roles = [m["role"] for m in ui_messages]
    assert "system" not in roles
    assert roles == ["user"]
