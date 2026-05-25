"""Tests for the slash-command registry and the channel surface.

Slash commands run over the one WebSocket now (`{"type":"slash"}`);
there is no REST command endpoint.
"""

from __future__ import annotations

import asyncio

import pytest

from app.chat import commands, pubsub
from tests._ws import ws_slash


def test_parse_command_accepts_bare_slash_token():
    assert commands.parse_command("/new") == "new"
    assert commands.parse_command("  /new  ") == "new"
    assert commands.parse_command("/foo") == "foo"


def test_parse_command_rejects_args_and_garbage():
    assert commands.parse_command("/new task") is None
    assert commands.parse_command("/new\ttask") is None
    assert commands.parse_command("hi") is None
    assert commands.parse_command("") is None
    assert commands.parse_command("/") is None
    assert commands.parse_command("not /new") is None


def test_list_commands_includes_new(client):
    body = client.get("/api/chat/commands").json()
    names = {c["name"]: c["description"] for c in body["commands"]}
    assert names["new"] == "Reset chat history"


def test_run_new_archives_messages_keeps_session(client, _test_db):
    from pydantic_ai.messages import ModelRequest, UserPromptPart

    from app.chat.models import ChatSession, Message
    from app.chat.service import save_new_messages

    sid = client.get("/api/chat/main").json()["session_id"]

    Session = _test_db
    msg = ModelRequest(parts=[UserPromptPart(content="hello")])
    with Session() as s:
        save_new_messages(s, sid, [msg])
        assert s.query(Message).filter(Message.session_id == sid).count() == 1

    # Sanity: history endpoint sees the message before /new.
    pre = client.get(f"/api/chat/sessions/{sid}/messages").json()
    assert len(pre["messages"]) == 1

    snap = ws_slash(client, session_id=sid, name="new")
    assert snap["messages"] == []

    with Session() as s:
        # Rows are stamped, not deleted, so they remain readable via
        # `search_main_chat_history`.
        rows = s.query(Message).filter(Message.session_id == sid).all()
        assert len(rows) == 1
        assert rows[0].archived_at is not None
        assert s.get(ChatSession, sid) is not None

    # The UI loader filters `archived_at IS NULL`, so the chat looks
    # empty after /new even though the row is still in the DB.
    post = client.get(f"/api/chat/sessions/{sid}/messages").json()
    assert post["messages"] == []


def test_run_new_isolated_to_target_session(client, _test_db):
    from pydantic_ai.messages import ModelRequest, UserPromptPart

    from app.chat.models import ChatSession, Message
    from app.chat.service import save_new_messages

    Session = _test_db
    with Session() as s:
        a, b = ChatSession(), ChatSession()
        s.add_all([a, b])
        s.commit()
        s.refresh(a)
        s.refresh(b)
        a_id, b_id = a.id, b.id

    msg = ModelRequest(parts=[UserPromptPart(content="hi")])
    with Session() as s:
        save_new_messages(s, a_id, [msg])
        save_new_messages(s, b_id, [msg])

    ws_slash(client, session_id=a_id, name="new")

    with Session() as s:
        a_rows = s.query(Message).filter(Message.session_id == a_id).all()
        assert len(a_rows) == 1
        assert a_rows[0].archived_at is not None

        b_rows = s.query(Message).filter(Message.session_id == b_id).all()
        assert len(b_rows) == 1
        assert b_rows[0].archived_at is None


def test_unknown_command_is_a_safe_noop(client):
    """An unknown slash name over the channel does nothing and leaves the
    socket usable."""
    sid = client.get("/api/chat/main").json()["session_id"]
    with client.websocket_connect("/api/ws") as ws:
        ws.send_json({"type": "subscribe", "session_ids": [sid]})
        assert ws.receive_json()["type"] == "snapshot"
        ws.send_json({"type": "slash", "session_id": sid, "name": "notreal"})
        # Still alive: a resync round-trips.
        ws.send_json({"type": "resync", "session_id": sid})
        assert ws.receive_json()["type"] == "snapshot"


def test_unknown_session_slash_is_a_safe_noop(client):
    with client.websocket_connect("/api/ws") as ws:
        ws.send_json({"type": "subscribe", "session_ids": [99999]})
        assert ws.receive_json()["type"] == "snapshot"
        ws.send_json({"type": "slash", "session_id": 99999, "name": "new"})
        ws.send_json({"type": "resync", "session_id": 99999})
        assert ws.receive_json()["type"] == "snapshot"


@pytest.mark.usefixtures("_test_db")
def test_handle_new_publishes_reset_event(_test_db):
    from app.chat.commands import _handle_new
    from app.chat.models import ChatSession

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
                _handle_new(s, sid)
            event = await asyncio.wait_for(q.get(), timeout=1.0)
            assert event == {"type": "reset"}

    asyncio.run(run())
