"""Streaming-write helpers.

The chat router persists agent output as it streams from pydantic-ai
(rather than once at end-of-turn) so a mid-stream disconnect or
provider timeout doesn't lose the partial response. The helpers below
back that flow: insert a row at the first `PartEndEvent`, rewrite its
`parts_json` as later events extend the message, and patch the final
metadata (usage / model / provider) once the stream resolves.

pubsub is intentionally silent here — the active HTTP client already
streams the deltas; cross-tab listeners refetch on `runner_finished`
(router-side) or on the runner's existing per-message publishes
(runner-side, which keeps using `save_new_messages` directly).
"""

from __future__ import annotations

from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
)
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.chat import pubsub
from app.chat.models import Message
from app.chat.service.publish import _publish_row_upsert
from app.chat.service.sessions import get_or_create_main_session


def _dump_single(message: ModelMessage) -> dict[str, Any]:
    """Round-trip one ModelMessage to the JSON blob shape stored in `parts_json`."""
    dumped = ModelMessagesTypeAdapter.dump_python([message], mode="json")
    blob = dumped[0]
    if not isinstance(blob, dict):  # pragma: no cover — adapter always returns dicts
        raise TypeError(f"ModelMessagesTypeAdapter dumped non-dict: {type(blob).__name__}")
    return blob


def _assign_response_metadata_columns(row: Message, blob: dict[str, Any]) -> None:
    row.usage_json = blob.get("usage")
    row.model_name = blob.get("model_name")
    row.provider = blob.get("provider_name")


def create_streaming_response_row(session: Session, session_id: int, text: str) -> Message:
    """Create the DB identity for a streaming assistant response.

    This intentionally does not fire push notifications. The row starts
    as a best-effort live partial; the final ModelResponse update is what
    represents a completed assistant message.
    """
    blob = ModelMessagesTypeAdapter.dump_python(
        [ModelResponse(parts=[TextPart(content=text)])],
        mode="json",
    )[0]
    row = Message(
        session_id=session_id,
        kind=blob.get("kind", "response"),
        parts_json=blob,
        usage_json=blob.get("usage"),
        model_name=blob.get("model_name"),
        provider=blob.get("provider_name"),
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
    if row is None or row.kind != "response":
        return None

    blob = ModelMessagesTypeAdapter.dump_python([message], mode="json")[0]
    row.parts_json = blob
    row.usage_json = blob.get("usage")
    row.model_name = blob.get("model_name")
    row.provider = blob.get("provider_name")
    flag_modified(row, "parts_json")
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
    far); subsequent `update_draft_response` calls overwrite the parts
    blob as new `PartEndEvent`s arrive. Push notifications fire only at
    `finalize_response_metadata`, not here.
    """
    blob = _dump_single(response)
    row = Message(
        session_id=session_id,
        source_session_id=source_session_id,
        kind="response",
        parts_json=blob,
    )
    _assign_response_metadata_columns(row, blob)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update_draft_response(
    session: Session,
    message_id: int,
    response: ModelResponse,
) -> None:
    """Overwrite `parts_json` for an in-flight response row."""
    blob = _dump_single(response)
    row = session.get(Message, message_id)
    if row is None:
        return
    row.parts_json = blob
    _assign_response_metadata_columns(row, blob)
    flag_modified(row, "parts_json")
    session.commit()


def start_tool_return_request(
    session: Session,
    session_id: int,
    request: ModelRequest,
    *,
    source_session_id: int | None = None,
) -> Message:
    """Insert a ModelRequest row holding the first ToolReturnPart of a turn."""
    blob = _dump_single(request)
    row = Message(
        session_id=session_id,
        source_session_id=source_session_id,
        kind="request",
        parts_json=blob,
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
    """Overwrite `parts_json` for an in-flight ToolReturnPart-carrying request."""
    blob = _dump_single(request)
    row = session.get(Message, message_id)
    if row is None:
        return
    row.parts_json = blob
    flag_modified(row, "parts_json")
    session.commit()


def finalize_response_metadata(
    session: Session,
    message_id: int,
    response: ModelResponse,
    *,
    fire_push: bool = True,
) -> Message | None:
    """Patch a draft response row with the final ModelResponse + side effects.

    The final ModelResponse carries `usage` / `model_name` /
    `provider_name`, which aren't present on per-PartEndEvent draft
    inserts. This call writes them in and (optionally) fires the
    assistant-message Web Push that `save_new_messages` would have
    triggered if we'd persisted the whole turn at once.
    """
    blob = _dump_single(response)
    row = session.get(Message, message_id)
    if row is None:
        return None
    row.parts_json = blob
    _assign_response_metadata_columns(row, blob)
    flag_modified(row, "parts_json")
    session.commit()
    session.refresh(row)
    if fire_push:
        from app.chat import service as _service  # late lookup so tests can monkeypatch

        main_session_id = get_or_create_main_session(session).id
        if row.session_id == main_session_id:
            _service._fire_assistant_message_push(row, row.session_id)
    return row
