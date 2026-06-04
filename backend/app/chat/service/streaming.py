"""Streaming-write helpers.

The chat router persists agent output as it streams from pydantic-ai
(rather than once at end-of-turn) so a mid-stream disconnect or
provider timeout doesn't lose the partial response. The helpers below
back that flow: insert a row at the first `PartEndEvent`, rebuild its
parts as later events extend the message, and patch the final message
once the stream resolves.

Each flush rebuilds the message's `MessagePart` rows via the mapper
(`set_message_parts`); `delete-orphan` cleans up the superseded parts.

pubsub is intentionally silent here — the active HTTP client already
streams the deltas; cross-tab listeners refetch on `runner_finished`
(router-side) or on the runner's existing per-message publishes
(runner-side, which keeps using `save_new_messages` directly).
"""

from __future__ import annotations

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
)
from sqlalchemy.orm import Session

from app.chat import pubsub
from app.chat.models import Message
from app.chat.persist.mapper import build_message_row, set_message_parts
from app.chat.service.publish import _publish_row_upsert
from app.chat.service.sessions import get_or_create_main_session


def create_streaming_response_row(session: Session, session_id: int, text: str) -> Message:
    """Create the DB identity for a streaming assistant response.

    This intentionally does not fire push notifications. The row starts
    as a best-effort live partial; the final ModelResponse update is what
    represents a completed assistant message.
    """
    row = build_message_row(
        ModelResponse(parts=[TextPart(content=text)]),
        session_id=session_id,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update_streaming_response_row(
    session: Session,
    row_id: int,
    message: ModelResponse,
    *,
    publish: bool = True,
    run_id: str | None = None,
) -> Message | None:
    """Replace a live partial response row with the final ModelResponse."""
    row = session.get(Message, row_id)
    if row is None or row.role != "response":
        return None

    set_message_parts(row, message)
    session.commit()
    session.refresh(row)

    from app.chat import service as _service  # late lookup so tests can monkeypatch

    main_session_id = get_or_create_main_session(session).id
    if row.session_id == main_session_id:
        _service._fire_assistant_message_push(row, row.session_id)
    if publish and not _publish_row_upsert(session, row.session_id, row.id, run_id=run_id):
        pubsub.publish(row.session_id, {"type": "messages_changed", "session_id": row.session_id})
    return row


def start_draft_response(
    session: Session,
    session_id: int,
    response: ModelResponse,
    *,
    source_session_id: int | None = None,
) -> Message:
    """Insert a partial assistant response row mid-stream.

    The row is fully-formed (carries whatever parts have completed so
    far); subsequent `update_draft_response` calls rebuild the parts as
    new `PartEndEvent`s arrive. Push notifications fire only at
    `finalize_response_metadata`, not here.
    """
    row = build_message_row(
        response,
        session_id=session_id,
        source_session_id=source_session_id,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update_draft_response(
    session: Session,
    message_id: int,
    response: ModelResponse,
) -> None:
    """Rebuild the parts for an in-flight response row."""
    row = session.get(Message, message_id)
    if row is None:
        return
    set_message_parts(row, response)
    session.commit()


def start_tool_return_request(
    session: Session,
    session_id: int,
    request: ModelRequest,
    *,
    source_session_id: int | None = None,
) -> Message:
    """Insert a ModelRequest row holding the first ToolReturnPart of a turn."""
    row = build_message_row(
        request,
        session_id=session_id,
        source_session_id=source_session_id,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update_tool_return_request(
    session: Session,
    message_id: int,
    request: ModelRequest,
) -> None:
    """Rebuild the parts for an in-flight ToolReturnPart-carrying request."""
    row = session.get(Message, message_id)
    if row is None:
        return
    set_message_parts(row, request)
    session.commit()


def finalize_response_metadata(
    session: Session,
    message_id: int,
    response: ModelResponse,
    *,
    fire_push: bool = True,
) -> Message | None:
    """Patch a draft response row with the final ModelResponse + side effects.

    The final ModelResponse carries the complete part set, which may
    differ from the per-PartEndEvent draft inserts. This call rebuilds
    the parts and (optionally) fires the assistant-message Web Push that
    `save_new_messages` would have triggered if we'd persisted the whole
    turn at once.
    """
    row = session.get(Message, message_id)
    if row is None:
        return None
    set_message_parts(row, response)
    session.commit()
    session.refresh(row)
    if fire_push:
        from app.chat import service as _service  # late lookup so tests can monkeypatch

        main_session_id = get_or_create_main_session(session).id
        if row.session_id == main_session_id:
            _service._fire_assistant_message_push(row, row.session_id)
    return row
