"""The seam between our DB schema and pydantic-ai's `ModelMessage` types.

Load: read a `Message` parent + its ordered `MessagePart` children, then
reassemble the pydantic-ai-shaped dict and let `ModelMessagesTypeAdapter`
validate it back into real `ModelRequest`/`ModelResponse` objects — so
multimodal content, provider fidelity fields, and tool pairing all
round-trip exactly.

Save: dump a `ModelMessage` once via the adapter, split its parts into
child rows, and promote the queried fields (`part_kind`, `tool_name`,
`tool_call_id`) to columns. The part body is stored faithfully in
`payload`; known tool calls/returns are additionally schema-validated.

Drift guard: `from_pydantic` rejects any unknown `part_kind` loudly
instead of silently dropping it — the agreed substitute for a golden
round-trip corpus.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter

from app.chat.models import Message, MessagePart
from app.chat.persist.tools import validate_tool_part

# Every part kind pydantic-ai can put in a request or a response. Used as
# the exhaustiveness guard on save: a new kind from a library upgrade
# fails here instead of being persisted half-formed.
_REQUEST_PART_KINDS = {"system-prompt", "user-prompt", "tool-return", "retry-prompt"}
_RESPONSE_PART_KINDS = {
    "text",
    "tool-call",
    "builtin-tool-call",
    "builtin-tool-return",
    "thinking",
    "compaction",
    "file",
}
KNOWN_PART_KINDS = _REQUEST_PART_KINDS | _RESPONSE_PART_KINDS


def _dump(message: ModelMessage) -> dict[str, Any]:
    dumped = ModelMessagesTypeAdapter.dump_python([message], mode="json")[0]
    if not isinstance(dumped, dict):  # pragma: no cover — adapter always returns dicts
        raise TypeError(f"adapter dumped non-dict: {type(dumped).__name__}")
    return dumped


def _build_parts(message: ModelMessage) -> tuple[str, str | None, list[MessagePart]]:
    """Split a ModelMessage into (role, instructions, ordered part rows)."""
    dumped = _dump(message)
    role = dumped["kind"]
    instructions = dumped.get("instructions") if role == "request" else None
    parts: list[MessagePart] = []
    for seq, payload in enumerate(dumped.get("parts") or []):
        part_kind = payload.get("part_kind")
        if part_kind not in KNOWN_PART_KINDS:
            raise ValueError(
                f"unknown part_kind {part_kind!r} — pydantic-ai schema changed; "
                "extend KNOWN_PART_KINDS and the mapper before persisting"
            )
        validate_tool_part(part_kind, payload)
        parts.append(
            MessagePart(
                seq=seq,
                part_kind=part_kind,
                tool_name=payload.get("tool_name"),
                tool_call_id=payload.get("tool_call_id"),
                payload=payload,
            )
        )
    return role, instructions, parts


def build_message_row(
    message: ModelMessage,
    *,
    session_id: int,
    source_session_id: int | None = None,
) -> Message:
    """Construct a parent `Message` with its part children (not yet committed)."""
    role, instructions, parts = _build_parts(message)
    row = Message(
        session_id=session_id,
        source_session_id=source_session_id,
        role=role,
        instructions=instructions,
    )
    row.parts = parts
    return row


def set_message_parts(row: Message, message: ModelMessage) -> None:
    """Replace a row's parts (and role/instructions) in place.

    Used by the streaming writers, which grow a single message across
    `PartEndEvent`s: each flush rebuilds that message's part rows.
    `cascade="all, delete-orphan"` on the relationship deletes the
    detached old parts on flush.
    """
    role, instructions, parts = _build_parts(message)
    row.role = role
    row.instructions = instructions
    row.parts = parts


def message_to_pydantic(row: Message) -> ModelMessage:
    """Reassemble one parent row + its parts into a pydantic-ai ModelMessage."""
    payload: dict[str, Any] = {
        "kind": row.role,
        "parts": [part.payload for part in row.parts],
    }
    if row.role == "request" and row.instructions is not None:
        payload["instructions"] = row.instructions
    return ModelMessagesTypeAdapter.validate_python([payload])[0]


def try_message_to_pydantic(row: Message) -> ModelMessage | None:
    """Like `message_to_pydantic` but returns None on validation failure."""
    try:
        return message_to_pydantic(row)
    except ValidationError:
        return None


def rows_to_pydantic(rows: list[Message]) -> list[ModelMessage]:
    return [message_to_pydantic(row) for row in rows]
