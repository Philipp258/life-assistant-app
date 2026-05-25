"""pubsub fan-out helpers for message upserts."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.chat import pubsub
from app.chat.service.ui_dump import _ui_message_by_row_id


def _publish_message_upsert(
    session_id: int,
    message: dict[str, Any],
    *,
    run_id: str | None = None,
) -> None:
    event: dict[str, Any] = {
        "type": "message_upsert",
        "session_id": session_id,
        "message": message,
    }
    if run_id is not None:
        event["run_id"] = run_id
    pubsub.publish(session_id, event)


def _publish_row_upsert(
    session: Session,
    session_id: int,
    row_id: int,
    *,
    run_id: str | None = None,
) -> bool:
    message = _ui_message_by_row_id(session, session_id, row_id)
    if message is None:
        return False
    _publish_message_upsert(session_id, message, run_id=run_id)
    return True


def publish_streaming_text_upsert(
    session_id: int,
    row_id: int,
    text: str,
    *,
    run_id: str | None = None,
) -> None:
    """Publish a live text-only assistant message with its persisted row id."""
    _publish_message_upsert(
        session_id,
        {
            "id": str(row_id),
            "role": "assistant",
            "parts": [{"type": "text", "text": text}],
        },
        run_id=run_id,
    )
