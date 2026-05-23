"""Web Push fan-out for assistant messages persisted to the main session."""

from __future__ import annotations

from pydantic_ai.messages import TextPart

from app.chat.models import Message
from app.chat.service.history import parse_message
from app.notifications import service as notify_service


def _extract_text_preview(row: Message, max_len: int = 140) -> str:
    """Build a short body string for a push notification from a saved row.

    Pulls the first text part out of the persisted Pydantic AI JSON blob.
    Falls back to an empty string if no text is found (e.g. a tool-only
    response). The push fan-out skips empty bodies.
    """
    msg = parse_message(row)
    if msg is None:
        return ""
    for part in msg.parts:
        if isinstance(part, TextPart):
            content = part.content
            if isinstance(content, str) and content.strip():
                text = content.strip()
                if len(text) > max_len:
                    text = text[: max_len - 1].rstrip() + "…"
                return text
    return ""


def _fire_assistant_message_push(row: Message, session_id: int) -> None:
    """Schedule a Web Push notification for a freshly-saved assistant message.

    Hidden import + centralized scheduling keeps this fire-and-forget:
    `save_new_messages` is sync (called from sync routes and from the
    runner via thread executors) and must not block on network I/O.
    """
    body = _extract_text_preview(row)
    if not body:
        return

    notify_service.schedule_notify(
        event_type="assistant_message",
        title="Life Assistant",
        body=body,
        url="/chat",
        quiet_if_session_id=session_id,
        tag=f"assistant_message:{session_id}",
    )
