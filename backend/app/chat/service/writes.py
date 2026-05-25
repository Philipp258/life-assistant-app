"""Bulk message persistence (`save_new_messages` + run-glue wrapper)."""

from __future__ import annotations

from collections.abc import Iterable

from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelResponse,
)
from sqlalchemy.orm import Session

from app.chat import pubsub
from app.chat.models import Message
from app.chat.service.publish import _publish_row_upsert
from app.chat.service.sessions import get_or_create_main_session


def save_new_messages(
    session: Session,
    session_id: int,
    messages: Iterable[ModelMessage],
    *,
    source_session_id: int | None = None,
    publish: bool = True,
) -> list[Message]:
    """Persist messages and publish each to the session's pubsub channel.

    `source_session_id` is stamped on every persisted row — set when the
    message originates from a *different* session via cross-session tooling.

    `publish=False` suppresses the pubsub fan-out when the writer's client
    is already seeing the same content via another channel — e.g. the chat
    router's streaming-event tap saves draft response rows from the same
    events the connected client is rendering, so re-publishing would only
    cause that client to re-fetch and re-mount its runtime. Push
    notifications still fire (they consult `subscriber_count` directly).
    """
    dumped = ModelMessagesTypeAdapter.dump_python(list(messages), mode="json")
    saved: list[Message] = []
    for blob in dumped:
        row = Message(
            session_id=session_id,
            source_session_id=source_session_id,
            kind=blob.get("kind", "request"),
            parts_json=blob,
        )
        if blob.get("kind") == "response":
            row.usage_json = blob.get("usage")
            row.model_name = blob.get("model_name")
            row.provider = blob.get("provider_name")
        session.add(row)
        saved.append(row)
    session.commit()
    main_session_id: int | None = None
    has_response = any(blob.get("kind") == "response" for blob in dumped)
    if has_response:
        # Only resolve main when there's actually a candidate to push for.
        # Looked up once per call so we don't hammer SELECT in fan-out.
        main_session_id = get_or_create_main_session(session).id
    from app.chat import service as _service  # late lookup so tests can monkeypatch

    for row in saved:
        session.refresh(row)
        if row.kind == "response" and session_id == main_session_id:
            _service._fire_assistant_message_push(row, session_id)
    if publish:
        # Prefer keyed row updates over a full snapshot. Some rows (tool
        # returns, hidden system context) do not map to standalone UI
        # messages; those still fall back to the snapshot poke because
        # they can change a previous assistant UIMessage's tool state.
        needs_snapshot = False
        for row in saved:
            if not _publish_row_upsert(session, session_id, row.id):
                needs_snapshot = True
        if needs_snapshot:
            pubsub.publish(session_id, {"type": "messages_changed", "session_id": session_id})
    return saved


def save_run_messages(
    session: Session,
    new_messages: list[ModelMessage],
    *,
    session_id: int,
    publish: bool = True,
) -> None:
    """Persist a run's new_messages to the given session."""
    save_new_messages(
        session,
        session_id,
        [m for m in new_messages if isinstance(m, ModelResponse) or m.kind == "request"],
        publish=publish,
    )
