"""History repair: heal partial state so the next agent turn loads cleanly.

Pydantic-AI history validation rejects a trailing assistant turn that
carries unresolved `tool_call_id`s — the next provider request would be
rejected. We can end up in that shape when persistence happens
incrementally during streaming and the stream is interrupted mid-tool
(client disconnect, provider timeout, process crash): the assistant's
tool-call ModelResponse is already on disk but the matching
ToolReturnPart never landed.

Two surfaces:

- `close_dangling_tool_calls(messages)` — in-memory list repair, kept
  for callers that already hold the assembled ModelMessage list
  (currently the runner's mid-turn error path).
- `repair_persisted_history(session, session_id)` — DB-level repair.
  Walks the visible rows for `session_id`, and if any tool calls lack
  matching returns, appends one synthetic ModelRequest row carrying
  placeholder ToolReturnParts. Idempotent — a second call finds no
  open calls and returns False without writing.
"""

from __future__ import annotations

from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ToolCallPart,
    ToolReturnPart,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chat.models import Message
from app.chat.service import save_new_messages

INTERRUPTED_MESSAGE = "Tool execution was interrupted by an error."


def _open_tool_calls(messages: list[ModelMessage]) -> dict[str, str]:
    """Return open tool_call_id → tool_name pairs (calls without returns)."""
    open_calls: dict[str, str] = {}
    for msg in messages:
        for part in msg.parts or []:
            if isinstance(part, ToolCallPart) and part.tool_call_id:
                open_calls[part.tool_call_id] = part.tool_name
            elif isinstance(part, ToolReturnPart) and part.tool_call_id:
                open_calls.pop(part.tool_call_id, None)
    return open_calls


def _build_repair_request(open_calls: dict[str, str]) -> ModelRequest:
    return ModelRequest(
        parts=[
            ToolReturnPart(
                tool_call_id=tid,
                tool_name=tname,
                content=INTERRUPTED_MESSAGE,
            )
            for tid, tname in open_calls.items()
        ]
    )


def close_dangling_tool_calls(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Append a synthetic ToolReturnPart-only ModelRequest for any open calls.

    Returns the input unchanged when every tool call already has a return.
    """
    open_calls = _open_tool_calls(messages)
    if not open_calls:
        return messages
    return [*messages, _build_repair_request(open_calls)]


def repair_persisted_history(session: Session, session_id: int) -> bool:
    """Persist a synthetic ToolReturnPart-only ModelRequest if needed.

    Loads the visible (non-archived) rows for `session_id`, detects any
    unresolved `tool_call_id`s, and appends one repair row through
    `save_new_messages` if so. Returns True when a row was written.

    Called at agent-turn entry by both router and runner so any
    partial-write breakage from a previous interrupted turn is healed
    before pydantic-ai validates the next history load.
    """
    rows = session.scalars(
        select(Message)
        .where(
            Message.session_id == session_id,
            Message.archived_at.is_(None),
        )
        .order_by(Message.id)
    ).all()
    if not rows:
        return False
    messages = list(ModelMessagesTypeAdapter.validate_python([row.parts_json for row in rows]))
    open_calls = _open_tool_calls(messages)
    if not open_calls:
        return False
    save_new_messages(session, session_id, [_build_repair_request(open_calls)], publish=False)
    return True
