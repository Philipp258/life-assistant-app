"""Pydantic AI tools for the onboarding ritual.

The agent picks up the user's name and chooses (or accepts) its own
name through ``set_user_name`` / ``set_assistant_name``. ``mark_onboarded``
stamps the user as done; it refuses unless both identity names are
already stored, so the post-onboarding system prompt can render its
``IDENTITY_PROMPT`` section without falling back to placeholders.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import Agent

from app.agent.deps import AgentDeps


def do_set_assistant_name(name: str) -> dict[str, Any]:
    from app.db import SessionLocal
    from app.knowledge import identity

    with SessionLocal() as db:
        try:
            stored = identity.set_assistant_name(db, name)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
    return {"ok": True, "assistant_name": stored}


def do_set_user_name(name: str) -> dict[str, Any]:
    from app.db import SessionLocal
    from app.knowledge import identity

    with SessionLocal() as db:
        try:
            stored = identity.set_user_name(db, name)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
    return {"ok": True, "user_name": stored}


def do_mark_onboarded() -> dict[str, Any]:
    from app.db import SessionLocal
    from app.knowledge import identity
    from app.users.service import mark_onboarded

    with SessionLocal() as db:
        if not identity.identity_complete(db):
            return {"ok": False, "error": "identity_incomplete"}
        wrote = mark_onboarded(db)
    return {"ok": True, "already_onboarded": not wrote}


def register(agent: Agent[AgentDeps, Any]) -> None:
    @agent.tool_plain
    def set_assistant_name(name: str) -> dict[str, Any]:
        """Store the name the user picked for you.

        Required during onboarding before ``mark_onboarded`` will succeed.
        """
        return do_set_assistant_name(name)

    @agent.tool_plain
    def set_user_name(name: str) -> dict[str, Any]:
        """Store the user's own name.

        Required during onboarding before ``mark_onboarded`` will succeed.
        """
        return do_set_user_name(name)

    @agent.tool_plain
    def mark_onboarded() -> dict[str, Any]:
        """Stamp the user as onboarded.

        Refuses with ``identity_incomplete`` unless both ``set_user_name``
        and ``set_assistant_name`` have already been called. Idempotent.
        """
        return do_mark_onboarded()
