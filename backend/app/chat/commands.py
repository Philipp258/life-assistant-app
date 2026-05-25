"""Slash command registry for chat sessions.

A command is parsed from the trailing `/<token>` text in a chat composer
and routed to a dedicated REST endpoint, not the agent run loop. Each
handler runs against a target ChatSession (main or task-bound).

Adding a command = define a handler and call `register(SlashCommand(...))`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.chat import pubsub
from app.chat.models import Message
from app.datetime_utils import utc_now


@dataclass(frozen=True)
class SlashCommand:
    name: str
    description: str
    handler: Callable[[Session, int], None]


REGISTRY: dict[str, SlashCommand] = {}


def register(cmd: SlashCommand) -> None:
    REGISTRY[cmd.name] = cmd


def get(name: str) -> SlashCommand | None:
    return REGISTRY.get(name)


def all_commands() -> list[SlashCommand]:
    return list(REGISTRY.values())


def parse_command(text: str) -> str | None:
    """Return command name if `text.strip()` is exactly `/<token>` with no args.

    Reject anything with whitespace or extra content after the token so a
    legitimate prose message that happens to start with `/foo bar` falls
    through to the agent.
    """
    if not text:
        return None
    stripped = text.strip()
    if len(stripped) < 2 or not stripped.startswith("/"):
        return None
    body = stripped[1:]
    if not body or any(ch.isspace() for ch in body):
        return None
    return body


def _handle_new(db: Session, session_id: int) -> None:
    # Stamp instead of delete so the rows remain readable via
    # `search_main_chat_history`. Already-archived rows keep their
    # original timestamp. Commit before publishing; `pubsub.publish` is
    # exception-safe (see app.chat.pubsub) so a failure there can't
    # leave clients out of sync with a committed reset.
    db.execute(
        update(Message)
        .where(Message.session_id == session_id, Message.archived_at.is_(None))
        .values(archived_at=utc_now())
    )
    db.commit()
    pubsub.publish(session_id, {"type": "reset"})


register(
    SlashCommand(
        name="new",
        description="Reset chat history",
        handler=_handle_new,
    )
)
