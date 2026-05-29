"""Task → main-session lifecycle handoff persistence."""

from __future__ import annotations

from pydantic_ai.messages import ModelRequest, SystemPromptPart
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chat.models import Message
from app.chat.service.history import parse_message
from app.chat.service.writes import save_new_messages
from app.datetime_utils import utc_now

TASK_HANDOFF_OPEN = "<task_handoff>"
TASK_HANDOFF_CLOSE = "</task_handoff>"


def format_task_handoff(handoff: str) -> str:
    """Wrap a task lifecycle handoff as hidden model context."""
    text = (handoff or "").strip()
    return f"{TASK_HANDOFF_OPEN}\n{text}\n{TASK_HANDOFF_CLOSE}"


def save_task_handoff(
    session: Session,
    session_id: int,
    handoff: str,
) -> Message | None:
    """Persist a task lifecycle handoff as a hidden main-chat event.

    The row is a valid ModelRequest containing only a SystemPromptPart,
    so normal UI rendering hides it. It is stamped compacted immediately:
    the main session still drains it as a task-terminal event
    (`app.chat.events`), but the task agent's future live-history loads
    do not replay internal handoff bookkeeping as conversation context.
    """
    text = (handoff or "").strip()
    if not text:
        return None
    message = ModelRequest(parts=[SystemPromptPart(content=format_task_handoff(text))])
    rows = save_new_messages(session, session_id, [message], publish=False)
    if not rows:
        return None
    row = rows[0]
    row.compacted_at = utc_now()
    session.commit()
    session.refresh(row)
    return row


def extract_task_handoff_text(content: str) -> str | None:
    text = (content or "").strip()
    if not text.startswith(TASK_HANDOFF_OPEN):
        return None
    body = text[len(TASK_HANDOFF_OPEN) :].strip()
    if body.endswith(TASK_HANDOFF_CLOSE):
        body = body[: -len(TASK_HANDOFF_CLOSE)].strip()
    return body or None


def latest_task_handoff(session: Session, session_id: int) -> str | None:
    """Return the newest hidden handoff string for a task chat."""
    rows = session.scalars(
        select(Message)
        .where(
            Message.session_id == session_id,
            Message.archived_at.is_(None),
        )
        .order_by(Message.id.desc())
        .limit(50)
    ).all()
    for row in rows:
        msg = parse_message(row)
        if msg is None:
            continue
        for part in msg.parts:
            if not isinstance(part, SystemPromptPart):
                continue
            handoff = extract_task_handoff_text(part.content)
            if handoff is not None:
                return handoff
    return None
