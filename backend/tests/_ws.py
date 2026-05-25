"""Test helper: drive one chat turn over the real WebSocket channel.

The channel (`app.chat.ws`) is the only turn-delivery path now — there
is no streaming POST. These helpers connect, subscribe, send input, and
collect the down-events (snapshots + runner/part deltas) so tests can
assert on real end-to-end behaviour exactly as the browser sees it.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from pydantic_ai import models

from app.agent import get_agent
from tests._function_model import build_function_model


def _collect_until(ws, terminal_type: str, *, limit: int = 200) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for _ in range(limit):
        event = ws.receive_json()
        events.append(event)
        if event.get("type") == terminal_type:
            return events
    raise AssertionError(
        f"did not see {terminal_type!r} within {limit} events: {[e.get('type') for e in events]}"
    )


@contextmanager
def ws_connect(client):
    with client.websocket_connect("/api/ws") as ws:
        yield ws


def ws_slash(client, *, session_id: int, name: str) -> dict[str, Any]:
    """Run a slash command over the channel; return the snapshot the
    server pushes once the command's write commits."""
    with client.websocket_connect("/api/ws") as ws:
        ws.send_json({"type": "subscribe", "session_ids": [session_id]})
        first = ws.receive_json()
        assert first["type"] == "snapshot", first
        ws.send_json({"type": "slash", "session_id": session_id, "name": name})
        for _ in range(50):
            event = ws.receive_json()
            if event.get("type") == "snapshot":
                return event
    raise AssertionError("no post-slash snapshot received")


def ws_turn(
    client,
    *,
    session_id: int,
    text: str,
    handler,
    voice: bool | None = None,
) -> list[dict[str, Any]]:
    """Send one user message over the channel and return every down-event
    up to and including `runner_finished`.

    `handler` is a plain `(messages, info) -> ModelResponse` function;
    it is wrapped for the streaming path automatically.
    """
    original_allow = models.ALLOW_MODEL_REQUESTS
    models.ALLOW_MODEL_REQUESTS = True
    try:
        agent = get_agent()
        with agent.override(model=build_function_model(handler)):
            with client.websocket_connect("/api/ws") as ws:
                ws.send_json({"type": "subscribe", "session_ids": [session_id]})
                # Initial subscribe snapshot.
                first = ws.receive_json()
                assert first["type"] == "snapshot", first
                payload: dict[str, Any] = {
                    "type": "input",
                    "session_id": session_id,
                    "text": text,
                }
                if voice is not None:
                    payload["voice"] = voice
                ws.send_json(payload)
                return [first, *_collect_until(ws, "runner_finished")]
    finally:
        models.ALLOW_MODEL_REQUESTS = original_allow


def last_snapshot(events: list[dict[str, Any]]) -> dict[str, Any]:
    snaps = [e for e in events if e.get("type") == "snapshot"]
    assert snaps, f"no snapshot in {[e.get('type') for e in events]}"
    return snaps[-1]


def reduce_messages(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for event in events:
        etype = event.get("type")
        if etype == "snapshot":
            messages = list(event.get("messages") or [])
        elif etype == "message_upsert":
            message = event.get("message")
            if not isinstance(message, dict):
                continue
            mid = message.get("id")
            idx = next((i for i, existing in enumerate(messages) if existing.get("id") == mid), -1)
            if idx >= 0:
                messages[idx] = message
            else:
                messages.append(message)
        elif etype == "message_delete":
            mid = event.get("id")
            messages = [message for message in messages if message.get("id") != mid]
        elif etype == "reset":
            messages = []
    return messages


def reduced_texts(events: list[dict[str, Any]], role: str) -> list[str]:
    return _message_texts(reduce_messages(events), role)


def snapshot_texts(snapshot: dict[str, Any], role: str) -> list[str]:
    return _message_texts(snapshot.get("messages", []), role)


def _message_texts(messages: list[dict[str, Any]], role: str) -> list[str]:
    out: list[str] = []
    for msg in messages:
        if msg.get("role") != role:
            continue
        for part in msg.get("parts", []) or []:
            if isinstance(part, dict) and part.get("type") == "text":
                t = part.get("text")
                if isinstance(t, str) and t.strip():
                    out.append(t.strip())
    return out
