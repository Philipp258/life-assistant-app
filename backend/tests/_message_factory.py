"""Test helpers for building persisted messages under the typed schema.

Mirrors the shape tests used to write directly (`Message(kind=...,
parts_json={"kind": ..., "parts": [...]})`) but produces the current
parent `Message` + ordered `MessagePart` children. Keeps test churn local
to one factory instead of every test hand-rolling part rows.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.chat.models import Message, MessagePart
from app.chat.persist.tools import validate_tool_part


def make_message(
    *,
    session_id: int,
    kind: str = "request",
    parts: list[dict[str, Any]] | None = None,
    parts_json: dict[str, Any] | None = None,
    source_session_id: int | None = None,
    instructions: str | None = None,
    created_at: datetime | None = None,
    compacted_at: datetime | None = None,
    archived_at: datetime | None = None,
) -> Message:
    """Build a Message + its MessagePart children (not yet added to a session)."""
    if parts is None:
        parts = (parts_json or {}).get("parts") or []
    if instructions is None and parts_json is not None:
        instructions = parts_json.get("instructions")
    row = Message(
        session_id=session_id,
        source_session_id=source_session_id,
        role=kind,
        instructions=instructions,
    )
    if created_at is not None:
        row.created_at = created_at
    if compacted_at is not None:
        row.compacted_at = compacted_at
    if archived_at is not None:
        row.archived_at = archived_at
    children: list[MessagePart] = []
    for seq, part in enumerate(parts):
        part_kind = part["part_kind"]
        validate_tool_part(part_kind, part)
        children.append(
            MessagePart(
                seq=seq,
                part_kind=part_kind,
                tool_name=part.get("tool_name"),
                tool_call_id=part.get("tool_call_id"),
                payload=part,
            )
        )
    row.parts = children
    return row


def message_payloads(row: Message) -> list[dict[str, Any]]:
    """The ordered part payloads of a message (the old `parts_json['parts']`)."""
    return [part.payload for part in row.parts]
