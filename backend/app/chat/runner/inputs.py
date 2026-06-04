"""Predicates over message rows: "is there fresh user input on this session?"

Used by both wake gating (a turn-based task wake only runs when there's
an unanswered user message at the tail) and the mid-turn stale-input
check (an autonomous task whose user posted while a wake was already
mid-run reloads history at the next safe boundary).
"""

from __future__ import annotations

from pydantic_ai.messages import UserPromptPart
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.chat.models import Message
from app.chat.service import parse_message


def _user_prompt_has_text(part: UserPromptPart) -> bool:
    content = part.content
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        for item in content:
            if isinstance(item, str) and item.strip():
                return True
            text = getattr(item, "text", None)
            if isinstance(text, str) and text.strip():
                return True
    return False


def _session_has_pending_user_input(db: Session, session_id: int) -> bool:
    """Whether there is an unanswered user message at the visible tail.

    User input arrives over the channel as a persisted user
    `ModelRequest` + a `schedule_wake`; this predicate lets that wake
    actually run a turn — for the main session, and for a task chat in
    turn-based mode (assignee='user': the user replied to a blocked
    task and expects exactly one agent turn).

    Choice widgets can append request-row metadata after the user's
    choice. Scan through that trailing metadata until either a real
    assistant response closes the input or a non-empty user prompt is found.
    """
    rows = db.scalars(
        select(Message)
        .where(Message.session_id == session_id, Message.archived_at.is_(None))
        .order_by(Message.id.desc())
        .limit(20)
        .options(selectinload(Message.parts))
    ).all()
    for row in rows:
        if row.role != "request":
            return False
        msg = parse_message(row)
        if msg is None:
            continue
        if any(
            isinstance(part, UserPromptPart) and _user_prompt_has_text(part) for part in msg.parts
        ):
            return True
    return False


def _is_user_or_relay_input_row(row: Message) -> bool:
    """Rows that should refresh an autonomous task's chat context."""
    if row.source_session_id is not None:
        return True
    if row.role != "request":
        return False
    msg = parse_message(row)
    if msg is None:
        return False
    return any(
        isinstance(part, UserPromptPart) and _user_prompt_has_text(part) for part in msg.parts
    )


def _has_new_task_input_since(db: Session, session_id: int, after_id: int) -> bool:
    rows = db.scalars(
        select(Message)
        .where(
            Message.session_id == session_id,
            Message.archived_at.is_(None),
            Message.id > after_id,
        )
        .order_by(Message.id.asc())
        .options(selectinload(Message.parts))
    ).all()
    return any(_is_user_or_relay_input_row(row) for row in rows)
