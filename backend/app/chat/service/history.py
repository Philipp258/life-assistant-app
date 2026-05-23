"""Read-side: load Message rows and decode their `parts_json` blobs."""

from __future__ import annotations

from pydantic import ValidationError
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    UserPromptPart,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chat.models import Message


def _load_rows_and_messages(
    session: Session, session_id: int
) -> tuple[list[Message], list[ModelMessage]]:
    """Read visible rows + their decoded ModelMessages.

    Archived rows (stamped by `/new`) are hidden from UI and agent.
    The originals stay in the DB and are reachable via the agent's
    `search_main_chat_history` tool. Compacted rows (stamped by
    main-chat compaction) stay visible to the user — only the agent's
    live loader filters those out.
    """
    rows = session.scalars(
        select(Message)
        .where(
            Message.session_id == session_id,
            Message.archived_at.is_(None),
        )
        .order_by(Message.created_at.asc(), Message.id.asc())
    ).all()
    if not rows:
        return [], []
    parsed = list(ModelMessagesTypeAdapter.validate_python([row.parts_json for row in rows]))
    return list(rows), parsed


def _load_model_messages(session: Session, session_id: int) -> list[ModelMessage]:
    _rows, messages = _load_rows_and_messages(session, session_id)
    return messages


def parse_message(row: Message) -> ModelMessage | None:
    """Validate one row's `parts_json` into a typed pydantic-ai ModelMessage.

    Returns None for rows whose blob fails validation (corrupted or
    written by a prior, incompatible schema). Lets callers walk
    `msg.parts` with isinstance instead of poking dict[str, Any].
    """
    try:
        return ModelMessagesTypeAdapter.validate_python([row.parts_json])[0]
    except ValidationError:
        return None


def load_session_history(session: Session, session_id: int) -> list[ModelMessage]:
    return _load_model_messages(session, session_id)


def load_session_history_with_cursor(
    session: Session, session_id: int
) -> tuple[list[ModelMessage], int]:
    rows, messages = _load_rows_and_messages(session, session_id)
    cursor = rows[-1].id if rows else 0
    return messages, cursor


def _is_compaction_summary_message(message: ModelMessage) -> bool:
    if not isinstance(message, ModelRequest):
        return False
    parts = message.parts or []
    if len(parts) != 1 or not isinstance(parts[0], UserPromptPart):
        return False
    content = parts[0].content
    return isinstance(content, str) and content.lstrip().startswith("<conversation_summary>")


def _load_live_messages(
    session: Session, session_id: int
) -> tuple[list[Message], list[ModelMessage]]:
    """Read uncompacted rows and decode their stored ModelMessages.

    Returns the row list (so callers can stamp `compacted_at` on
    specific rows) alongside the parsed ModelMessage list.
    """
    rows = session.scalars(
        select(Message)
        .where(
            Message.session_id == session_id,
            Message.compacted_at.is_(None),
            Message.archived_at.is_(None),
        )
        .order_by(Message.created_at.asc(), Message.id.asc())
    ).all()
    if not rows:
        return [], []
    parsed = list(ModelMessagesTypeAdapter.validate_python([row.parts_json for row in rows]))
    paired = list(zip(rows, parsed, strict=True))
    # Summary rows are inserted after the live tail in DB order, but they
    # represent the oldest context. Keep row/message alignment while presenting
    # summaries first to the agent and to later compaction passes.
    paired.sort(
        key=lambda item: (
            not _is_compaction_summary_message(item[1]),
            item[0].created_at,
            item[0].id,
        )
    )
    return [row for row, _message in paired], [message for _row, message in paired]
