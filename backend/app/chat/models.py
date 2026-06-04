from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class ChatSession(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('main', 'agent', 'task')",
            name="ck_sessions_kind",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str | None] = mapped_column(String(128), nullable=True)
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(8), nullable=False, server_default="task", index=True)
    # High-water cursor over task-terminal events this session has already
    # drained (see `app.chat.events`). Plain integer (not an FK) so a
    # deleted handoff row can't reset it and re-flood the consumer —
    # exactly-once survives message deletion. NULL = nothing drained yet.
    # Only the singleton main session consumes events; task chats leave
    # this NULL.
    event_cursor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), index=True
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        foreign_keys="Message.session_id",
    )


class Message(Base):
    """One persisted pydantic-ai `ModelMessage` (a request or a response).

    This is the *parent* row. Its content lives in ordered `MessagePart`
    children — we persist a typed, owned schema rather than the external
    library's wire format, and map to/from pydantic-ai at the
    `app.chat.persist.mapper` seam on every load/save. Message-level
    response metadata (usage/model/provider) is intentionally not stored:
    it was write-only and is never sent back to a provider.
    """

    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('request', 'response')",
            name="ck_messages_role",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    # `ModelRequest.instructions` — request-level, rarely populated. Kept
    # so the mapper round-trips it without inventing a part kind for it.
    instructions: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), index=True
    )
    compacted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    session: Mapped[ChatSession] = relationship(
        back_populates="messages",
        foreign_keys=[session_id],
    )
    parts: Mapped[list["MessagePart"]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        order_by="MessagePart.seq",
        foreign_keys="MessagePart.message_id",
    )


class MessagePart(Base):
    """One typed part of a message (text, tool-call, tool-return, …).

    `part_kind` is the discriminator (mirrors pydantic-ai's `part_kind`).
    `tool_name` / `tool_call_id` are promoted to columns because we query
    and pair on them (UI rendering, history repair). `payload` carries the
    faithful part body; for tool calls/returns of known tools it is
    validated against `app.chat.persist.tools`.
    """

    __tablename__ = "message_parts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    part_kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    tool_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    payload: Mapped[Any] = mapped_column(JSON, nullable=False)

    message: Mapped[Message] = relationship(
        back_populates="parts",
        foreign_keys=[message_id],
    )
