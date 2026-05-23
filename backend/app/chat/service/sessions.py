"""ChatSession lookup + singleton main session bootstrap."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chat.models import ChatSession


def get_or_create_main_session(session: Session) -> ChatSession:
    """Singleton main session (`kind='main'`).

    Picks the oldest matching session as canonical when multiple exist
    (defensive — the migration backfills exactly one main row).
    """
    row = session.scalars(
        select(ChatSession)
        .where(ChatSession.kind == "main")
        .order_by(ChatSession.id.asc())
        .limit(1)
    ).first()
    if row is not None:
        return row
    row = ChatSession(kind="main")
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def get_session(session: Session, session_id: int) -> ChatSession | None:
    return session.get(ChatSession, session_id)
