"""The one bidirectional channel — end-to-end behaviour.

Covers the invariants the rebuild rests on: an `input` persists the
user message and runs exactly one turn that streams over the socket;
the DB is the source of truth and `resync` replays it; an autonomous
wake streams the *same* events an input turn does; single-flight holds.
"""

from __future__ import annotations

import asyncio

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo

from app.agent import get_agent
from app.chat import pubsub, runner
from app.chat.models import ChatSession, Message
from app.chat.service import get_or_create_main_session, save_new_messages, save_task_handoff
from app.tasks.models import Task
from tests._function_model import build_function_model
from tests._ws import reduced_texts, snapshot_texts, ws_turn


def _reply(text: str):
    def handler(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content=text)])

    return handler


def test_input_persists_user_message_and_streams_one_turn(client, _test_db):
    Session = _test_db
    main_id = client.get("/api/chat/main").json()["session_id"]

    events = ws_turn(
        client, session_id=main_id, text="hello there", handler=_reply("general kenobi")
    )
    types = [e["type"] for e in events]

    assert "runner_started" in types
    assert "runner_finished" in types
    assert types.index("runner_started") < types.index("runner_finished")
    assert "message_upsert" in types, f"no live message stream in {types}"

    assert "hello there" in reduced_texts(events, "user")
    assert "general kenobi" in reduced_texts(events, "assistant")

    with Session() as s:
        rows = s.query(Message).filter(Message.session_id == main_id).order_by(Message.id).all()
    kinds = [r.kind for r in rows]
    assert kinds.count("request") >= 1 and kinds.count("response") == 1, kinds


def test_resync_replays_db_snapshot(client, _test_db):
    Session = _test_db
    main_id = client.get("/api/chat/main").json()["session_id"]

    with client.websocket_connect("/api/ws") as ws:
        ws.send_json({"type": "subscribe", "session_ids": [main_id]})
        first = ws.receive_json()
        assert first["type"] == "snapshot"
        assert first["messages"] == []

        # A write the socket never saw (publish=False → no live poke).
        from pydantic_ai.messages import ModelRequest, UserPromptPart

        with Session() as s:
            save_new_messages(
                s,
                main_id,
                [
                    ModelRequest(parts=[UserPromptPart(content="offline question")]),
                    ModelResponse(parts=[TextPart(content="offline answer")]),
                ],
                publish=False,
            )

        ws.send_json({"type": "resync", "session_id": main_id})
        snap = ws.receive_json()
        assert snap["type"] == "snapshot"
        assert "offline question" in snapshot_texts(snap, "user")
        assert "offline answer" in snapshot_texts(snap, "assistant")


def test_snapshot_reports_idle_run_state(client):
    main_id = client.get("/api/chat/main").json()["session_id"]

    with client.websocket_connect("/api/ws") as ws:
        ws.send_json({"type": "subscribe", "session_ids": [main_id]})
        snap = ws.receive_json()
        assert snap["type"] == "snapshot"
        # No wake is in flight, so the authoritative snapshot tells the
        # client the composer is free — this is what heals a stuck spinner
        # after a missed runner_finished.
        assert snap["is_running"] is False


def test_task_updates_forward_over_session_subscription(client):
    created = client.post("/api/tasks", json={"title": "Watch me"})
    assert created.status_code == 201
    task_id = created.json()["id"]
    session_id = created.json()["chat_session_id"]

    with client.websocket_connect("/api/ws") as ws:
        ws.send_json({"type": "subscribe", "session_ids": [session_id]})
        first = ws.receive_json()
        assert first["type"] == "snapshot"

        patched = client.patch(f"/api/tasks/{task_id}", json={"title": "Watched"})
        assert patched.status_code == 200

        event = ws.receive_json()
        assert event["type"] == "task_upsert"
        assert event["session_id"] == session_id
        assert event["task_id"] == task_id
        assert event["task"]["title"] == "Watched"


def _wake_event_types(session_id: int, handler) -> list[str]:
    """Drive one autonomous wake while subscribed to pubsub directly, so
    publisher and subscriber share one event loop."""
    seen: list[str] = []

    async def run() -> None:
        async with pubsub.subscribe(session_id) as q:
            agent = get_agent()
            with agent.override(model=build_function_model(handler)):
                wake = asyncio.create_task(runner.wake_session(session_id))
                while True:
                    try:
                        ev = await asyncio.wait_for(q.get(), timeout=5.0)
                    except asyncio.TimeoutError:
                        break
                    seen.append(ev.get("type"))
                    if ev.get("type") == "runner_finished":
                        break
                await wake

    asyncio.run(run())
    return seen


def test_autonomous_wake_streams_same_events_as_input(client, _test_db):
    """A background-task-triggered main wake produces the same event
    shape as a user input turn — runner_started, token deltas, a
    committed row update, runner_finished."""
    Session = _test_db
    with Session() as s:
        main_id = get_or_create_main_session(s).id
        chat = ChatSession()
        s.add(chat)
        s.flush()
        task = Task(title="weather", assignee="user", chat_session_id=chat.id, is_done=False)
        s.add(task)
        s.flush()
        chat.task_id = task.id
        s.commit()
        save_task_handoff(s, chat.id, "Cologne tomorrow: rain.")

    types = _wake_event_types(main_id, _reply("It will rain in Cologne tomorrow."))

    assert "runner_started" in types
    assert "part_delta" in types
    assert "message_upsert" in types
    assert types[-1] == "runner_finished"


def test_single_flight_one_turn_under_concurrent_wakes(_test_db):
    """Two wakes racing the same session run exactly one turn — the
    per-session lock is unchanged by the channel."""
    Session = _test_db
    with Session() as s:
        main_id = get_or_create_main_session(s).id
        from pydantic_ai.messages import ModelRequest, UserPromptPart

        save_new_messages(s, main_id, [ModelRequest(parts=[UserPromptPart(content="ping")])])

    calls = 0

    def handler(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        return ModelResponse(parts=[TextPart(content="pong")])

    async def run() -> None:
        agent = get_agent()
        with agent.override(model=build_function_model(handler)):
            await asyncio.gather(
                runner.wake_session(main_id),
                runner.wake_session(main_id),
            )

    asyncio.run(run())

    # The trailing user message is consumed by the first turn; the second
    # wake finds it answered and is a no-op.
    assert calls == 1, f"agent ran {calls}x — single-flight/gate broke"
    with Session() as s:
        responses = (
            s.query(Message)
            .filter(Message.session_id == main_id, Message.kind == "response")
            .count()
        )
    assert responses == 1
